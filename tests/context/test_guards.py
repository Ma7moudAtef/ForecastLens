"""T1–T6: the six things context-aware forecasting must not get wrong.

Every one of these runs the WHOLE pipeline on a generated shape, because the
guards are only meaningful end to end — a diagnostic that fires correctly but
a selection layer that ignores it would pass a unit test and fail a planner.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.config import EngineConfig
from core.models.registry import CONTEXT_MODEL_NAMES
from core.pipeline import run_forecast
from core.store.repository import Repository
from tests.fixtures.synthetic import context_shapes as shapes


def _run(tmp_path, name, **kwargs):
    path, truth = shapes.workbook(name, tmp_path, **kwargs)
    db = tmp_path / f"{name}.db"
    run_id = run_forecast(path, EngineConfig(), db)
    with Repository(db) as repo:
        return {
            "truth": truth,
            "context": repo.get_series_context().set_index("series_id"),
            "selections": repo.get_selections(run_id).set_index("series_id"),
            "validation": repo.get_validation_results(run_id),
        }


# --- T1 -----------------------------------------------------------------------

def test_t1_single_stream_switches_the_layer_off(tmp_path):
    """One unit, one stream: nothing to compare. The layer must say so, offer
    no context model, and leave the forecast exactly as it would have been."""
    out = _run(tmp_path, "single_stream")
    row = out["context"].loc["SS001|u1|s1"]

    assert row["material"] == 0
    assert row["tested"] == 0
    assert "single unit" in row["skip_reason"]
    # no crash, no warning, no candidate — it simply does not apply
    assert not set(out["validation"]["model_name"]) & set(CONTEXT_MODEL_NAMES)
    assert out["selections"].loc["SS001|u1|s1", "model_name"] \
        not in CONTEXT_MODEL_NAMES


def test_t1_single_stream_matches_a_run_with_context_disabled(tmp_path):
    """The silent degradation has to be genuinely silent: identical numbers."""
    path, _ = shapes.workbook("single_stream", tmp_path)

    forecasts = []
    for enabled in (True, False):
        cfg = EngineConfig()
        cfg.context.enabled = enabled
        db = tmp_path / f"ss_{enabled}.db"
        run_id = run_forecast(path, cfg, db)
        with Repository(db) as repo:
            fc = repo.get_forecasts(run_id).sort_values(["series_id", "period"])
        forecasts.append(fc["target_value"].to_numpy(dtype=float))

    assert np.array_equal(forecasts[0], forecasts[1])


# --- T2 -----------------------------------------------------------------------

def test_t2_multi_regime_effect_is_found_and_used(tmp_path):
    """Consumption really is higher when both units run. The diagnosis has to
    find that, and a context model has to earn the series on validation."""
    out = _run(tmp_path, "multi_regime")
    series = out["truth"]["affected_series"]
    row = out["context"].loc[series]

    assert row["material"] == 1
    assert row["p_value"] < 0.05
    # the generator built a 40% lift; the measured spread must be in that
    # neighbourhood, not merely non-zero
    assert 0.20 < row["spread_pct"] < 0.60
    assert row["n_regimes"] == 2
    assert out["selections"].loc[series, "model_name"] in CONTEXT_MODEL_NAMES

    reason = out["selections"].loc[series, "reason_text"]
    assert "MASE" not in reason          # planner language only
    assert "validation error" in reason


def test_t2_unaffected_series_is_left_alone(tmp_path):
    """The second unit in the same workbook only ever runs under one
    condition, so nothing is claimed about it."""
    out = _run(tmp_path, "multi_regime")
    row = out["context"].loc["MR002|u2|s1"]

    assert row["material"] == 0
    assert "nothing to compare" in row["verdict"]
    assert out["selections"].loc["MR002|u2|s1", "model_name"] \
        not in CONTEXT_MODEL_NAMES


# --- T3 -----------------------------------------------------------------------

def test_t3_supplied_calendar_factor_is_found_and_used(tmp_path):
    """A promotion the driver table cannot express, supplied by the planner,
    must behave exactly like a derived condition."""
    out = _run(tmp_path, "promotions")
    series = out["truth"]["affected_series"]
    row = out["context"].loc[series]

    assert row["material"] == 1
    assert 0.20 < row["spread_pct"] < 0.55
    assert "promotion on" in row["verdict"]
    assert out["selections"].loc[series, "model_name"] in CONTEXT_MODEL_NAMES


def test_t3_calendar_factor_becomes_an_ordinary_feature(tmp_path):
    from core.config import EngineConfig as _Cfg
    from core.context import features as F
    from core.io.excel_source import ExcelSource
    from core.prep.series_builder import build_series

    path, _ = shapes.workbook("promotions", tmp_path)
    raw = ExcelSource(path).load()
    cfg = _Cfg()
    prep = build_series(raw, cfg)
    frame = F.derive(prep.driver_agg, cfg, calendar=raw.context_calendar)

    assert "ctx_promotion" in frame.calendar_features
    assert "ctx_promotion" in frame.feature_names
    # and it is folded into the operating condition, not bolted on beside it
    assert any("promotion=1" in label for label in frame.regime_counts)


# --- T4: guard G1, future availability ----------------------------------------

def test_t4_no_driver_plan_means_no_context_models(tmp_path):
    """Every context regressor is read from the plan. Without a plan covering
    the horizon nobody knows next month's conditions, so the models are
    withheld — and the reason is stated, not swallowed."""
    shape = shapes.multi_regime()
    prod = shape.sheets["prod"]
    shape.sheets["prod"] = prod[prod["production_type"] == "actual"]
    path = shapes.write(shape, tmp_path / "no_plan.xlsx")

    db = tmp_path / "no_plan.db"
    run_id = run_forecast(path, EngineConfig(), db)
    with Repository(db) as repo:
        context = repo.get_series_context().set_index("series_id")
        selections = repo.get_selections(run_id).set_index("series_id")

    row = context.loc["MR001|u1|s1"]
    assert row["material"] == 0
    assert "horizon" in row["verdict"]
    assert selections.loc["MR001|u1|s1", "model_name"] not in CONTEXT_MODEL_NAMES


def test_t4_context_features_never_look_ahead(tmp_path):
    """Utilization is scaled by a historical high-water mark. If the future
    could move that mark, past feature values would change whenever a plan
    was edited — so it is computed from actuals only."""
    from core.config import EngineConfig as _Cfg
    from core.context import features as F
    from core.io.excel_source import ExcelSource
    from core.prep.series_builder import build_series

    path, _ = shapes.workbook("multi_regime", tmp_path)
    raw = ExcelSource(path).load()
    cfg = _Cfg()
    prep = build_series(raw, cfg)

    full = F.derive(prep.driver_agg, cfg)
    actual_only = prep.driver_agg[prep.driver_agg["driver_type"] == "actual"]
    trimmed = F.derive(actual_only, cfg)

    key = ["period", "unit", "stream"]
    a = full.frame[full.frame["driver_type"] == "actual"].set_index(key)
    b = trimmed.frame.set_index(key)
    common = a.index.intersection(b.index)
    for column in ("utilization", "own_share", "system_driver", "n_active",
                   "regime_label"):
        left = a.loc[common, column]
        right = b.loc[common, column]
        assert left.equals(right), f"{column} changed when a plan was added"


# --- T5: guard G2, minimum support --------------------------------------------

def test_t5_rare_regimes_are_pooled_not_fitted(tmp_path):
    """A condition seen twice cannot support its own level. It joins an
    'other' bucket — pooled, never dropped, never fitted alone."""
    import pandas as pd

    from core.context.features import OTHER_REGIME, pool_rare_regimes

    labels = pd.Series(["a"] * 10 + ["b"] * 6 + ["c"] * 2 + ["d"])
    pooled = pool_rare_regimes(labels, min_obs=4)

    assert set(pooled.unique()) == {"a", "b", OTHER_REGIME}
    assert (pooled == OTHER_REGIME).sum() == 3       # nothing was thrown away
    assert len(pooled) == len(labels)


def test_t5_regime_model_refuses_without_two_supported_regimes():
    from core.context.matrix import ContextWindow
    from core.models.context_models import RegimeConditional

    n = 14
    # one big regime plus a pair of two-observation regimes: after pooling
    # the 'other' bucket holds 4, so exactly two levels are supportable
    regimes = np.array(["solo"] * 10 + ["x"] * 2 + ["y"] * 2, dtype=object)
    y = np.concatenate([np.full(10, 5.0), np.full(2, 9.0), np.full(2, 9.4)])
    window = ContextWindow(
        names=[], X=np.zeros((n, 0)), regimes=regimes,
        driver=np.ones(n), system_driver=np.ones(n),
        future_X=np.zeros((3, 0)),
        future_regimes=np.array(["solo"] * 3, dtype=object),
        future_driver=np.ones(3), future_system_driver=np.ones(3))

    model = RegimeConditional(min_regime_obs=4)
    model.set_context(window)
    model.fit(y)
    assert set(model.levels_) == {"solo", "other"}
    assert model.counts_["other"] == 4

    # raise the bar past what the data supports and it must refuse, not guess
    strict = RegimeConditional(min_regime_obs=12)
    strict.set_context(window)
    with pytest.raises(ValueError, match="two operating patterns"):
        strict.fit(y)


# --- T6: the overfitting guard, the important one -----------------------------

def test_t6_pure_noise_never_gets_a_context_model(tmp_path):
    """The trap. Identical operating variety to the multi_regime shape and no
    context effect whatsoever. Anything that claims to explain this series is
    fitting noise."""
    out = _run(tmp_path, "pure_noise")
    series = out["truth"]["noise_series"]
    row = out["context"].loc[series]

    assert row["material"] == 0
    assert row["p_value"] > 0.05
    assert out["selections"].loc[series, "model_name"] not in CONTEXT_MODEL_NAMES


def test_t6_pure_noise_survives_a_disabled_materiality_gate(tmp_path):
    """The materiality gate is the first defence, not the only one. Force the
    context models into the competition on pure noise and they must still
    lose it — out-of-sample validation is what actually protects the planner.
    """
    path, truth = shapes.workbook("pure_noise", tmp_path)
    cfg = EngineConfig()
    cfg.context.materiality = 0.0        # no effect-size bar
    cfg.context.alpha = 0.999            # no significance bar

    db = tmp_path / "forced.db"
    run_id = run_forecast(path, cfg, db)
    with Repository(db) as repo:
        selections = repo.get_selections(run_id).set_index("series_id")
        validation = repo.get_validation_results(run_id)

    series = truth["noise_series"]
    competed = validation[(validation["series_id"] == series)
                          & validation["model_name"].isin(CONTEXT_MODEL_NAMES)]
    assert not competed.empty, "the gate was disabled, so they must compete"
    assert selections.loc[series, "model_name"] not in CONTEXT_MODEL_NAMES


def test_t6_rejection_is_explained_in_plain_language(tmp_path):
    import json

    path, truth = shapes.workbook("pure_noise", tmp_path)
    cfg = EngineConfig()
    cfg.context.materiality = 0.0
    cfg.context.alpha = 0.999
    db = tmp_path / "forced_reasons.db"
    run_id = run_forecast(path, cfg, db)
    with Repository(db) as repo:
        selections = repo.get_selections(run_id).set_index("series_id")

    rejected = json.loads(
        selections.loc[truth["noise_series"], "rejected_json"])
    notes = {r["model_name"]: r["reason"] for r in rejected}
    context_notes = [notes[n] for n in CONTEXT_MODEL_NAMES if n in notes]

    assert context_notes, "context models should appear among the rejected"
    for note in context_notes:
        assert note and note[0].isupper()
        assert "MASE" not in note
        assert "Traceback" not in note
