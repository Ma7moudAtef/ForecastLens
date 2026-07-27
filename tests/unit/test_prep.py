import numpy as np
import pandas as pd

from core.config import EngineConfig, Granularity
from core.io.schema import build_raw_tables
from core.prep.calendar import days_in_period, to_period_index
from core.prep.mode import Mode, ModeSource, resolve_mode
from core.prep.series_builder import build_series

CFG = EngineConfig()


# --- calendar -----------------------------------------------------------------

def test_days_in_period_monthly_handles_leap():
    idx = pd.PeriodIndex(["2024-02", "2025-02", "2024-01", "2024-04"], freq="M")
    assert list(days_in_period(idx)) == [29, 28, 31, 30]


def test_days_in_period_weekly_daily():
    w = pd.PeriodIndex(["2024-01-01"], freq="W")
    d = pd.PeriodIndex(["2024-01-01"], freq="D")
    assert list(days_in_period(w)) == [7]
    assert list(days_in_period(d)) == [1]


def test_to_period_index_granularities():
    dates = pd.Series(pd.to_datetime(["2024-01-15", "2024-01-31"]))
    assert list(to_period_index(dates, Granularity.MONTHLY).astype(str)) == \
        ["2024-01", "2024-01"]
    assert to_period_index(dates, Granularity.DAILY).nunique() == 2


# --- mode resolution ----------------------------------------------------------

def test_mode_inference():
    assert resolve_mode(True) == (Mode.RELATIVE, ModeSource.INFERRED)
    assert resolve_mode(False) == (Mode.ABSOLUTE, ModeSource.INFERRED)


def test_declared_mode_always_wins_over_inference():
    # data says relative (rate present), planner declares absolute
    assert resolve_mode(True, declared_bom="absolute") == \
        (Mode.ABSOLUTE, ModeSource.DECLARED_BOM)
    # data says absolute, planner declares relative
    assert resolve_mode(False, declared_bom="Relative") == \
        (Mode.RELATIVE, ModeSource.DECLARED_BOM)


def test_ui_declaration_wins_over_bom():
    assert resolve_mode(True, declared_bom="absolute", declared_ui="relative") == \
        (Mode.RELATIVE, ModeSource.DECLARED_UI)


def test_invalid_declaration_falls_back_to_inference():
    assert resolve_mode(True, declared_bom="sideways") == \
        (Mode.RELATIVE, ModeSource.INFERRED)


# --- series builder -----------------------------------------------------------

def _bom_row(**kw):
    base = {"item_code": "A1", "item_description": "w", "uom": "p",
            "unit_price_$": 1.0, "unit_wt_kg": 0.1, "category_level1": "c1",
            "category_level2": "c2", "category_level3": "c3"}
    base.update(kw)
    return base


def _cons_row(**kw):
    base = {"date": "2024-01-01", "item_code": "A1", "cons_qty_base_uom": 10.0,
            "cons_qty_ton": 0.5, "cons_$": 100.0, "output_type": "x",
            "production_line": "a", "cons_rate": None, "cons_rate_uom": None}
    base.update(kw)
    return base


def _prod_row(**kw):
    base = {"date": "2024-01-01", "production_uom1": "t",
            "production_qty1": 100.0, "production_uom2": "s",
            "production_qty2": 5.0, "output_type": "x", "production_line": "a",
            "production_type": "actual"}
    base.update(kw)
    return base


def test_duplicates_summed_and_gaps_filled():
    raw = build_raw_tables({
        "bom": pd.DataFrame([_bom_row()]),
        "consumption": pd.DataFrame([
            _cons_row(cons_qty_base_uom=10.0),
            _cons_row(cons_qty_base_uom=5.0),          # duplicate period
            _cons_row(date="2024-03-01", cons_qty_base_uom=31.0),  # gap in Feb
        ]),
    })
    prep = build_series(raw, CFG)
    assert len(prep.series) == 1
    obs = prep.observations
    assert list(obs["period"]) == ["2024-01", "2024-02", "2024-03"]
    assert obs.loc[0, "qty_base"] == 15.0          # summed duplicates
    assert obs.loc[1, "qty_base"] == 0.0           # explicit zero demand
    assert obs.loc[1, "is_gap_filled"] == 1        # …but flagged as gap
    assert obs.loc[2, "is_gap_filled"] == 0


def test_absolute_target_is_per_day_normalized():
    raw = build_raw_tables({
        "bom": pd.DataFrame([_bom_row()]),
        "consumption": pd.DataFrame([
            _cons_row(date="2024-01-01", cons_qty_base_uom=31.0),
            _cons_row(date="2024-02-01", cons_qty_base_uom=29.0),  # leap Feb
        ]),
    })
    obs = build_series(raw, CFG).observations
    assert np.allclose(obs["target"], [1.0, 1.0])  # constant per-day demand


def test_relative_target_is_rate_and_driver_joined():
    raw = build_raw_tables({
        "bom": pd.DataFrame([_bom_row()]),
        "consumption": pd.DataFrame([
            _cons_row(cons_rate=0.5, cons_rate_uom="p/t"),
            _cons_row(date="2024-02-01", cons_rate=0.7, cons_rate_uom="p/t"),
        ]),
        "prod": pd.DataFrame([
            _prod_row(date="2024-01-01", production_qty1=100.0),
            _prod_row(date="2024-02-01", production_qty1=200.0),
        ]),
    })
    prep = build_series(raw, CFG)
    s = prep.series.iloc[0]
    assert s["mode"] == "relative" and s["is_orphan"] == 0
    obs = prep.observations
    assert list(obs["target"]) == [0.5, 0.7]
    assert list(obs["driver_qty"]) == [100.0, 200.0]
    assert s["target_uom"] == "p/t"


def test_low_driver_periods_marked_unreliable():
    rows, prows = [], []
    for m, qty in zip(range(1, 7), [100, 100, 100, 100, 100, 1]):
        rows.append(_cons_row(date=f"2024-0{m}-01", cons_rate=0.5))
        prows.append(_prod_row(date=f"2024-0{m}-01", production_qty1=float(qty)))
    raw = build_raw_tables({
        "bom": pd.DataFrame([_bom_row()]),
        "consumption": pd.DataFrame(rows),
        "prod": pd.DataFrame(prows),
    })
    prep = build_series(raw, CFG)
    obs = prep.observations
    assert list(obs["is_reliable"]) == [1, 1, 1, 1, 1, 0]
    assert prep.series.iloc[0]["n_reliable"] == 5
    assert any(w.code == "LOW_DRIVER_PERIODS" for w in prep.warnings)


def test_zero_driver_never_crashes():
    raw = build_raw_tables({
        "bom": pd.DataFrame([_bom_row()]),
        "consumption": pd.DataFrame([_cons_row(cons_rate=0.5)]),
        "prod": pd.DataFrame([_prod_row(production_qty1=0.0)]),
    })
    prep = build_series(raw, CFG)  # must not raise
    assert prep.observations.loc[0, "is_reliable"] == 0


def test_orphan_series_stays_relative_with_no_reliable_periods():
    raw = build_raw_tables({
        "bom": pd.DataFrame([_bom_row()]),
        "consumption": pd.DataFrame(
            [_cons_row(cons_rate=0.5, output_type="C")]),
        "prod": pd.DataFrame([_prod_row(output_type="x")]),
    })
    s = build_series(raw, CFG).series.iloc[0]
    assert s["mode"] == "relative"      # NEVER flips to absolute
    assert s["is_orphan"] == 1
    assert s["n_reliable"] == 0         # falls through the cold-start ladder


def test_declared_mode_override_applies():
    raw = build_raw_tables({
        "bom": pd.DataFrame([_bom_row()]),
        "consumption": pd.DataFrame([_cons_row(cons_rate=0.5)]),
        "prod": pd.DataFrame([_prod_row()]),
    })
    prep = build_series(raw, CFG, mode_overrides={"A1": "absolute"})
    s = prep.series.iloc[0]
    assert s["mode"] == "absolute" and s["mode_source"] == "declared_ui"


def test_driverless_dataset_all_absolute():
    """Trading / e-commerce shape: no prod sheet, no rates — zero code changes."""
    raw = build_raw_tables({
        "bom": pd.DataFrame([_bom_row()]),
        "consumption": pd.DataFrame([
            _cons_row(), _cons_row(date="2024-02-01", cons_qty_base_uom=29.0)]),
    })
    prep = build_series(raw, CFG)
    assert (prep.series["mode"] == "absolute").all()
    assert prep.series.iloc[0]["is_orphan"] == 0
    assert (prep.observations["is_reliable"] == 1).all()
