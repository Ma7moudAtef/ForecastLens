"""Zero rate + zero driver is 'the line did not run', not zero demand.

A period with no consumption rate AND no production has no meaningful rate:
the denominator does not exist. Treating it as a zero would inflate ADI (so
steady materials look intermittent) and drag every average down.
"""
import numpy as np
import pandas as pd

from core.analyze.statistics import analyze_all
from core.config import EngineConfig
from core.io.schema import build_raw_tables
from core.prep.series_builder import build_series

CFG = EngineConfig()


def _bom():
    return pd.DataFrame([{
        "item_code": "A1", "item_description": "w", "uom": "p",
        "unit_price_$": 1.0, "unit_wt_kg": 0.1, "category_level1": "c1",
        "category_level2": "c2", "category_level3": "c3"}])


def _cons(month, rate, qty=1.0):
    return {"date": f"2024-{month:02d}-01", "item_code": "A1",
            "cons_qty_base_uom": qty, "cons_qty_ton": qty / 1000,
            "cons_$": 1.0, "output_type": "x", "production_line": "a",
            "cons_rate": rate, "cons_rate_uom": "p/t"}


def _prod(month, qty):
    return {"date": f"2024-{month:02d}-01", "production_uom1": "t",
            "production_qty1": qty, "production_uom2": "s",
            "production_qty2": 1.0, "output_type": "x",
            "production_line": "a", "production_type": "actual"}


def _build(cons_rows, prod_rows):
    raw = build_raw_tables({"bom": _bom(),
                            "consumption": pd.DataFrame(cons_rows),
                            "prod": pd.DataFrame(prod_rows)})
    return build_series(raw, CFG)


def test_zero_rate_with_zero_driver_is_not_applicable():
    prep = _build(
        [_cons(1, 0.5), _cons(2, 0.0, qty=0.0), _cons(3, 0.5)],
        [_prod(1, 100.0), _prod(2, 0.0), _prod(3, 100.0)])
    obs = prep.observations
    assert list(obs["is_applicable"]) == [1, 0, 1]
    assert prep.series.iloc[0]["n_applicable"] == 2
    assert any(w.code == "NO_OUTPUT_PERIOD" for w in prep.warnings)


def test_zero_rate_with_real_production_stays_a_genuine_zero():
    """The line ran but this material was not consumed — that IS zero demand
    and must keep counting."""
    prep = _build(
        [_cons(1, 0.5), _cons(2, 0.0, qty=0.0), _cons(3, 0.5)],
        [_prod(1, 100.0), _prod(2, 100.0), _prod(3, 100.0)])
    assert list(prep.observations["is_applicable"]) == [1, 1, 1]
    assert not any(w.code == "NO_OUTPUT_PERIOD" for w in prep.warnings)


def test_missing_driver_record_with_no_rate_is_not_applicable():
    prep = _build(
        [_cons(1, 0.5), _cons(2, 0.0, qty=0.0)],
        [_prod(1, 100.0)])                       # no driver row for month 2
    assert list(prep.observations["is_applicable"]) == [1, 0]


def test_nonzero_rate_with_zero_driver_stays_applicable_but_unreliable():
    """A rate against a zero driver is suspicious, not meaningless — it is
    flagged unreliable, but it is real recorded data."""
    prep = _build(
        [_cons(1, 0.5), _cons(2, 0.7)],
        [_prod(1, 100.0), _prod(2, 0.0)])
    obs = prep.observations
    assert list(obs["is_applicable"]) == [1, 1]
    assert list(obs["is_reliable"]) == [1, 0]


def test_absolute_series_are_always_applicable():
    raw = build_raw_tables({
        "bom": _bom(),
        "consumption": pd.DataFrame([
            {**_cons(1, None), "cons_rate": None},
            {**_cons(2, None, qty=0.0), "cons_rate": None}]),
    })
    prep = build_series(raw, CFG)
    assert (prep.observations["is_applicable"] == 1).all()


def test_shutdown_periods_do_not_make_a_steady_item_look_intermittent():
    """The behavioural point of the rule: a plant that stopped for four
    months must not turn a smooth material into an intermittent one."""
    steady = [_cons(m, 0.5) for m in (1, 2, 3, 4)]
    shutdown = [_cons(m, 0.0, qty=0.0) for m in (5, 6, 7, 8)]
    resumed = [_cons(m, 0.5) for m in (9, 10, 11, 12)]
    prod_on = [_prod(m, 100.0) for m in (1, 2, 3, 4, 9, 10, 11, 12)]
    prod_off = [_prod(m, 0.0) for m in (5, 6, 7, 8)]

    prep = _build(steady + shutdown + resumed, prod_on + prod_off)
    analyzed = analyze_all(prep, CFG)
    row = analyzed.iloc[0]
    assert row["pattern_class"] == "smooth"
    assert row["adi"] == 1.0             # every counted period has demand

    # …whereas counting the shutdown as zeros would have made it intermittent
    from core.analyze.classify import classify
    with_zeros = np.array([0.5] * 4 + [0.0] * 4 + [0.5] * 4)
    assert classify(with_zeros)[0].value == "intermittent"
