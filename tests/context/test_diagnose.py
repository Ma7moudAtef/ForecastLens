"""The diagnostic layer: it runs for every series, and it says no often."""
from __future__ import annotations

import numpy as np
import pytest

from core.config import EngineConfig
from core.context import diagnose as D


def _cfg(**context):
    cfg = EngineConfig()
    for key, value in context.items():
        setattr(cfg.context, key, value)
    return cfg


def _split(low, high, n=12, spread=0.05, seed=0):
    """n periods under each of two conditions, with a little noise."""
    rng = np.random.default_rng(seed)
    y = np.concatenate([rng.normal(low, low * spread, n),
                        rng.normal(high, high * spread, n)])
    regimes = np.array(["solo"] * n + ["shared"] * n, dtype=object)
    return y, regimes


def test_a_real_difference_is_found_and_called_material():
    y, regimes = _split(5.0, 7.0)
    diag = D.diagnose(y, regimes, _cfg())

    assert diag.tested is True
    assert diag.p_value < 0.05
    assert diag.effect_size > 0.5
    assert diag.spread_pct == pytest.approx(2.0 / 6.0, rel=0.15)
    assert diag.material is True
    assert "higher" in diag.verdict


def test_a_tiny_difference_is_significant_but_not_material():
    """The whole point of the effect-size bar: with clean data a 2%
    difference is statistically certain and practically worthless."""
    y, regimes = _split(5.0, 5.1, n=30, spread=0.01)
    diag = D.diagnose(y, regimes, _cfg())

    assert diag.p_value < 0.05          # significant
    assert diag.spread_pct < 0.10       # but small
    assert diag.material is False
    assert "not worth forecasting separately" in diag.verdict


def test_pure_noise_is_not_called_a_pattern():
    rng = np.random.default_rng(7)
    y = rng.normal(5.0, 1.0, 40)
    regimes = np.array(["solo", "shared"] * 20, dtype=object)
    diag = D.diagnose(y, regimes, _cfg())

    assert diag.material is False
    assert diag.p_value > 0.05
    assert "looks the same" in diag.verdict


def test_one_condition_only_is_reported_not_tested():
    y = np.arange(10, dtype=float)
    regimes = np.array(["solo"] * 10, dtype=object)
    diag = D.diagnose(y, regimes, _cfg())

    assert diag.tested is False
    assert diag.material is False
    assert "nothing to compare" in diag.verdict
    assert "only one operating condition" in diag.skip_reason


def test_a_constant_series_cannot_be_explained_by_anything():
    y = np.full(20, 4.0)
    regimes = np.array(["solo"] * 10 + ["shared"] * 10, dtype=object)
    diag = D.diagnose(y, regimes, _cfg())

    assert diag.material is False
    assert "never varies" in diag.verdict


def test_too_little_history_says_so():
    diag = D.diagnose(np.array([1.0, 2.0]),
                      np.array(["a", "b"], dtype=object), _cfg())
    assert diag.tested is False
    assert "too little usable history" in diag.verdict


def test_unusable_periods_are_excluded_the_same_way_fitting_excludes_them():
    y, regimes = _split(5.0, 7.0)
    valid = np.ones(len(y), dtype=bool)
    valid[len(y) // 2:] = False          # drop the whole 'shared' condition

    diag = D.diagnose(y, regimes, _cfg(), valid=valid)
    assert diag.tested is False
    assert "only one operating condition" in diag.skip_reason


def test_rare_conditions_are_pooled_before_testing():
    """Two observations cannot be a regime of their own, but they must not
    vanish from the comparison either."""
    y = np.concatenate([np.full(10, 5.0) + 0.01, np.full(10, 7.0),
                        np.full(2, 9.0)])
    regimes = np.array(["solo"] * 10 + ["shared"] * 10 + ["rare"] * 2,
                       dtype=object)
    diag = D.diagnose(y, regimes, _cfg(min_regime_obs=4))

    assert "rare" not in diag.counts
    assert diag.counts["other"] == 2
    assert diag.n_observations == 22


def test_effect_size_is_bounded():
    assert D._eta_squared(0.0, 2, 20) == 0.0
    assert D._eta_squared(1e6, 2, 20) == 1.0
    assert D._eta_squared(5.0, 2, 2) is None


def test_the_materiality_threshold_is_configurable():
    y, regimes = _split(5.0, 6.0)        # ~18% spread
    assert D.diagnose(y, regimes, _cfg(materiality=0.10)).material is True
    assert D.diagnose(y, regimes, _cfg(materiality=0.50)).material is False


def test_a_misaligned_context_is_refused_not_guessed():
    diag = D.diagnose(np.arange(10, dtype=float),
                      np.array(["a"] * 4, dtype=object), _cfg())
    assert diag.tested is False
    assert "not aligned" in diag.skip_reason


def test_the_row_written_to_the_store_is_flat_and_complete():
    y, regimes = _split(5.0, 7.0)
    row = D.diagnose(y, regimes, _cfg()).to_row()

    assert set(row) == {"tested", "n_regimes", "n_observations", "p_value",
                        "effect_size", "spread_pct", "material", "verdict",
                        "regime_counts_json", "skip_reason"}
    assert row["material"] in (0, 1)
    assert isinstance(row["regime_counts_json"], str)


def test_the_rejection_note_says_which_bar_was_missed():
    small, regimes = _split(5.0, 5.1, n=30, spread=0.01)
    note = D.rejection_note(D.diagnose(small, regimes, _cfg()), _cfg())
    assert "too small" in note

    rng = np.random.default_rng(3)
    noise = rng.normal(5.0, 1.0, 40)
    flat = np.array(["solo", "shared"] * 20, dtype=object)
    note = D.rejection_note(D.diagnose(noise, flat, _cfg()), _cfg())
    assert "does not differ measurably" in note
