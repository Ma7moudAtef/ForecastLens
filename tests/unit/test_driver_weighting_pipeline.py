"""The driver reaches the averaging models — end to end, not just in unit
tests of the models themselves.

Trap 2 lives in tests/traps/. This file proves the wiring: that the driver a
series was consumed against actually arrives at Mean / MovingAverage /
WeightedMovingAverage through the pipeline's context building, and that
periods excluded from fitting carry no weight.
"""
import numpy as np
import pandas as pd
import pytest

from core.analyze.statistics import analyze_all
from core.config import EngineConfig
from core.io.schema import build_raw_tables
from core.models.averaging import MovingAverage, WeightedMovingAverage
from core.models.baselines import Mean
from core.pipeline import build_contexts
from core.prep.series_builder import build_series

CFG = EngineConfig()


def _workbook(rates, drivers, qty=1.0):
    bom = pd.DataFrame([{
        "item_code": "A1", "item_description": "w", "uom": "p",
        "unit_price_$": 1.0, "unit_wt_kg": 0.1, "category_level1": "c1",
        "category_level2": "c2", "category_level3": "c3"}])
    cons = pd.DataFrame([{
        "date": f"2024-{m:02d}-01", "item_code": "A1",
        "cons_qty_base_uom": qty, "cons_qty_ton": qty / 1000, "cons_$": 1.0,
        "output_type": "x", "production_line": "a", "cons_rate": r,
        "cons_rate_uom": "p/t"} for m, r in enumerate(rates, start=1)])
    prod = pd.DataFrame([{
        "date": f"2024-{m:02d}-01", "production_uom1": "t",
        "production_qty1": d, "production_uom2": "s", "production_qty2": 1.0,
        "output_type": "x", "production_line": "a",
        "production_type": "actual"} for m, d in enumerate(drivers, start=1)])
    return build_raw_tables({"bom": bom, "consumption": cons, "prod": prod})


def _context(rates, drivers):
    raw = _workbook(rates, drivers)
    prep = build_series(raw, CFG)
    analyzed = analyze_all(prep, CFG)
    contexts = build_contexts(prep, analyzed, raw.items, raw.standard_rates,
                              {}, CFG)
    return contexts[0]


def test_relative_context_carries_the_driver():
    ctx = _context([0.5, 0.4, 0.6, 0.5, 0.5, 0.5],
                   [100.0, 120.0, 90.0, 110.0, 100.0, 100.0])
    assert ctx.mode == "relative"
    assert ctx.driver is not None
    assert np.allclose(ctx.driver, [100, 120, 90, 110, 100, 100])


def test_absolute_context_has_no_driver():
    bom = pd.DataFrame([{
        "item_code": "A1", "item_description": "w", "uom": "p",
        "unit_price_$": 1.0, "unit_wt_kg": 0.1, "category_level1": "c1",
        "category_level2": "c2", "category_level3": "c3"}])
    cons = pd.DataFrame([{
        "date": f"2024-{m:02d}-01", "item_code": "A1",
        "cons_qty_base_uom": 5.0, "cons_qty_ton": 0.005, "cons_$": 1.0,
        "output_type": "x", "production_line": "a", "cons_rate": None,
        "cons_rate_uom": None} for m in range(1, 7)])
    raw = build_raw_tables({"bom": bom, "consumption": cons})
    prep = build_series(raw, CFG)
    analyzed = analyze_all(prep, CFG)
    ctx = build_contexts(prep, analyzed, raw.items, raw.standard_rates,
                         {}, CFG)[0]
    assert ctx.driver is None


def test_averaging_models_use_the_pipeline_driver():
    """Unequal — but all reliable — drivers: the weighted level must equal
    ΣC/ΣP and differ clearly from the plain mean.

    The drivers stay within the reliability floor (20% of the series median)
    on purpose: a driver far below that is excluded from fitting entirely,
    which is a different rule tested below.
    """
    rates = [1.0, 0.1, 1.0, 0.1, 1.0, 0.1]
    drivers = [100.0, 300.0, 100.0, 300.0, 100.0, 300.0]
    ctx = _context(rates, drivers)
    assert not np.isnan(ctx.driver).any(), "fixture drove a period below the floor"

    weighted = float(np.sum(np.array(rates) * np.array(drivers))
                     / np.sum(drivers))                      # 0.325
    plain = float(np.mean(rates))                            # 0.55

    level = Mean().fit(ctx.y, driver=ctx.driver).predict(1)[0]
    assert level == pytest.approx(weighted)
    assert abs(level - plain) > 0.2

    ma = MovingAverage(3).fit(ctx.y, driver=ctx.driver)
    assert bool(ma.params()["driver_weighted"])
    wma = WeightedMovingAverage(3).fit(ctx.y, driver=ctx.driver)
    assert bool(wma.params()["driver_weighted"])


def test_periods_excluded_from_fitting_carry_no_weight():
    """A period whose driver collapsed is unreliable and its target is
    interpolated — letting the real driver vote for a synthetic value would
    bias the average."""
    rates = [0.5, 0.5, 0.5, 9.9, 0.5, 0.5]
    drivers = [100.0, 100.0, 100.0, 0.5, 100.0, 100.0]   # month 4 collapsed
    ctx = _context(rates, drivers)

    assert np.isnan(ctx.driver[3]), "unreliable period still carries weight"
    level = Mean().fit(ctx.y, driver=ctx.driver).predict(1)[0]
    assert level == pytest.approx(0.5, abs=1e-9)   # the spike cannot leak in


def test_not_applicable_periods_carry_no_weight():
    rates = [0.5, 0.5, 0.0, 0.5, 0.5, 0.5]
    drivers = [100.0, 100.0, 0.0, 100.0, 100.0, 100.0]   # shutdown in month 3
    ctx = _context(rates, drivers)
    assert np.isnan(ctx.driver[2])
    level = Mean().fit(ctx.y, driver=ctx.driver).predict(1)[0]
    assert level == pytest.approx(0.5)
