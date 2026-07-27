import numpy as np
import pytest

from core.config import EngineConfig
from core.selection import gate
from core.selection.gate import Route
from core.selection.select import SeriesContext, select_for_series

CFG = EngineConfig()


def _ctx(y, mode="absolute", pattern="smooth", **kw):
    y = np.asarray(y, dtype=float)
    defaults = dict(
        series_id="t|a|x", mode=mode, pattern_class=pattern,
        n_reliable=len(y), y=y, valid=np.ones(len(y), dtype=bool),
        driver=None)
    defaults.update(kw)
    return SeriesContext(**defaults)


# --- gate ---------------------------------------------------------------------

def test_gate_routes_intermittent_and_lumpy():
    for cls in ("intermittent", "lumpy"):
        d = gate.decide(30, cls, "absolute", CFG)
        assert d.route is Route.ROUTED_INTERMITTENT
        names = {c.name for c in d.candidates}
        assert names == {"SBA", "TSB", "Croston", "ZeroForecast"}


def test_gate_cold_start_below_six():
    d = gate.decide(5, "too_short", "relative", CFG)
    assert d.route is Route.COLD_START
    assert d.candidates == []


def test_gate_nonseasonal_set_6_to_23():
    d = gate.decide(12, "smooth", "absolute", CFG)
    assert d.route is Route.COMPETE
    names = {c.name for c in d.candidates}
    assert {"Naive", "Drift", "Mean", "SES", "DampedHolt", "Theta",
            "MovingAverage"} <= names
    assert "SeasonalNaive" not in names
    assert "HoltWinters" not in names


def test_gate_full_set_at_24():
    d = gate.decide(30, "smooth", "absolute", CFG)
    names = {c.name for c in d.candidates}
    assert {"SeasonalNaive", "Holt", "HoltWinters", "ETS"} <= names
    assert "ARIMA" not in names             # off by default


def test_gate_arima_only_when_enabled():
    cfg = EngineConfig()
    cfg.models.enable_arima = True
    names = {c.name for c in gate.decide(30, "smooth", "absolute", cfg).candidates}
    assert "ARIMA" in names
    # …and even enabled, never below 24 periods
    names_short = {c.name for c in gate.decide(20, "smooth", "absolute", cfg).candidates}
    assert "ARIMA" not in names_short


def test_gate_respects_disabled_models():
    cfg = EngineConfig()
    cfg.models.disabled_models = ["Theta", "SES"]
    names = {c.name for c in gate.decide(12, "smooth", "absolute", cfg).candidates}
    assert "Theta" not in names and "SES" not in names


# --- selection ----------------------------------------------------------------

def test_trend_series_selects_a_trend_capable_model():
    rng = np.random.default_rng(7)
    y = 5.0 * np.arange(30) + 20 + rng.normal(0, 1.5, 30)
    sel = select_for_series(_ctx(y), CFG)
    assert sel.route == "compete"
    assert sel.winner_name in {"DampedHolt", "Holt", "Drift", "Theta", "ETS",
                               "ARIMA", "Ensemble"}


def test_stable_series_selects_a_simple_level_model():
    rng = np.random.default_rng(11)
    y = 100.0 + rng.normal(0, 2, 30)
    sel = select_for_series(_ctx(y), CFG)
    assert sel.winner_name in {"Mean", "SES", "MovingAverage",
                               "WeightedMovingAverage", "Naive", "Ensemble",
                               "ETS", "Theta"}


def test_cold_start_ladder_relative_prefers_standard_rate():
    y = np.array([0.004, 0.005])
    sel = select_for_series(
        _ctx(y, mode="relative", pattern="too_short", n_reliable=2,
             std_rate=0.0045), CFG)
    assert sel.route == "cold_start"
    assert sel.winner_name == "StandardRateAnchor"
    assert sel.reason_code == "cold_start_standard_rate"
    assert sel.validation_skipped


def test_cold_start_ladder_falls_to_category_prior_then_naive():
    y = np.array([3.0, 4.0])
    sel = select_for_series(
        _ctx(y, pattern="too_short", n_reliable=2, prior_value=3.6,
             prior_level=3, prior_siblings=9, prior_category="fasteners"), CFG)
    assert sel.winner_name == "CategoryPrior"
    sel2 = select_for_series(_ctx(y, pattern="too_short", n_reliable=2), CFG)
    assert sel2.winner_name == "Naive"


def test_relative_cold_start_never_flips_mode():
    """A Relative series with no usable driver history lands in the ladder
    but its context stays relative — mode is a property of the material."""
    y = np.zeros(4)
    sel = select_for_series(
        _ctx(y, mode="relative", pattern="too_short", n_reliable=0), CFG)
    assert sel.route == "cold_start"
    assert sel.winner_name == "ZeroForecast"  # no signal at all, honest zero


def test_intermittent_routed_to_sba_by_default():
    y = np.array([0.0, 5, 0, 0, 6, 0, 0, 5, 0, 0, 6, 0], dtype=float)
    sel = select_for_series(
        _ctx(y, pattern="intermittent", trailing_zeros=1, median_interval=3.0),
        CFG)
    assert sel.route == "routed_intermittent"
    assert sel.winner_name == "SBA"
    assert sel.validation_skipped


def test_obsolescent_series_routed_to_tsb():
    y = np.concatenate([np.array([5.0, 0, 5, 0, 5, 0]), np.zeros(10)])
    sel = select_for_series(
        _ctx(y, pattern="intermittent", trailing_zeros=10, median_interval=2.0),
        CFG)
    assert sel.winner_name == "TSB"
    assert sel.reason_code == "routed_tsb_obsolescence"


def test_planner_override_is_respected():
    rng = np.random.default_rng(3)
    y = 100.0 + rng.normal(0, 2, 30)
    sel = select_for_series(_ctx(y, override_model="Drift"), CFG)
    assert sel.winner_name == "Drift"
    assert sel.is_override
    assert sel.reason_code == "planner_override"
    # the competition table is preserved for comparison
    assert len(sel.candidates) > 3


def test_selection_is_deterministic():
    rng = np.random.default_rng(5)
    y = 50 + rng.normal(0, 3, 26)
    a = select_for_series(_ctx(y), CFG)
    b = select_for_series(_ctx(y.copy()), CFG)
    assert (a.winner_name, a.winner_window) == (b.winner_name, b.winner_window)
    assert a.mase == pytest.approx(b.mase)
