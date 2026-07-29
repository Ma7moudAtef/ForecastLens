import pandas as pd

from core.config import EngineConfig
from core.io.schema import build_raw_tables
from core.validate import rules


def _sheets(cons_rows, prod_rows=None, bom_rows=None):
    bom = pd.DataFrame(bom_rows or [{
        "item_code": "A1", "item_description": "w", "uom": "p",
        "unit_price_$": 1.0, "unit_wt_kg": 0.1,
        "category_level1": "c1", "category_level2": "c2", "category_level3": "c3",
    }])
    cons = pd.DataFrame(cons_rows)
    sheets = {"bom": bom, "consumption": cons}
    if prod_rows is not None:
        sheets["prod"] = pd.DataFrame(prod_rows)
    return sheets


def _cons_row(**kw):
    base = {
        "date": "2024-01-01", "item_code": "A1", "cons_qty_base_uom": 10.0,
        "cons_qty_ton": 0.5, "cons_$": 100.0, "output_type": "x",
        "production_line": "a", "cons_rate": None, "cons_rate_uom": None,
    }
    base.update(kw)
    return base


def _prod_row(**kw):
    base = {
        "date": "2024-01-01", "production_uom1": "t", "production_qty1": 100.0,
        "production_uom2": "s", "production_qty2": 5.0, "output_type": "x",
        "production_line": "a", "production_type": "actual",
    }
    base.update(kw)
    return base


CFG = EngineConfig()


def _codes(warnings):
    return {w.code for w in warnings}


def test_orphan_series_detected_and_named():
    raw = build_raw_tables(_sheets(
        [_cons_row(cons_rate=0.5, output_type="C")],
        prod_rows=[_prod_row(output_type="x")]))
    ws = rules.rule_orphan_series(raw, CFG)
    assert len(ws) == 1
    w = ws[0]
    assert w.code == "ORPHAN_SERIES"
    assert w.item_code == "A1" and w.output_type == "C"
    assert "denominator does not exist" in w.message
    assert "forecast ABSOLUTE" in w.message
    assert "nothing is deleted" in w.message


def test_orphan_not_raised_when_combo_exists():
    raw = build_raw_tables(_sheets(
        [_cons_row(cons_rate=0.5)], prod_rows=[_prod_row()]))
    assert rules.rule_orphan_series(raw, CFG) == []


def test_rates_without_any_driver_table():
    raw = build_raw_tables(_sheets([_cons_row(cons_rate=0.5)]))
    ws = rules.rule_rates_without_driver_table(raw, CFG)
    assert len(ws) == 1
    assert ws[0].code == "RATES_WITHOUT_DRIVER_TABLE"


def test_missing_driver_periods_is_gap_not_mode_change():
    raw = build_raw_tables(_sheets(
        [_cons_row(cons_rate=0.5, date="2024-01-01"),
         _cons_row(cons_rate=0.6, date="2024-02-01")],
        prod_rows=[_prod_row(date="2024-01-01")]))
    ws = rules.rule_missing_driver_periods(raw, CFG)
    assert len(ws) == 1
    assert ws[0].count == 1
    assert "mode unchanged" in ws[0].message


def test_duplicate_rows_flagged():
    raw = build_raw_tables(_sheets([_cons_row(), _cons_row()]))
    ws = rules.rule_duplicate_rows(raw, CFG)
    assert len(ws) == 1 and ws[0].code == "DUPLICATE_PERIOD_ROWS"


def test_negative_and_missing_quantities():
    raw = build_raw_tables(_sheets([
        _cons_row(cons_qty_base_uom=-5),
        _cons_row(date="2024-02-01", cons_qty_base_uom=None),
    ]))
    all_w = rules.run_all(raw, CFG)
    assert {"NEGATIVE_VALUE", "MISSING_QUANTITY"} <= _codes(all_w)


def test_mixed_mode_series_flagged():
    raw = build_raw_tables(_sheets([
        _cons_row(cons_rate=0.5),
        _cons_row(date="2024-02-01", cons_rate=None),
    ], prod_rows=[_prod_row()]))
    ws = rules.rule_mixed_mode_series(raw, CFG)
    assert len(ws) == 1
    assert "Relative" in ws[0].message


def test_invalid_declared_mode_flagged():
    sheets = _sheets([_cons_row()])
    sheets["bom"]["mode"] = ["sideways"]
    raw = build_raw_tables(sheets)
    ws = rules.rule_invalid_declared_mode(raw, CFG)
    assert len(ws) == 1 and ws[0].code == "INVALID_DECLARED_MODE"


def test_nonpositive_driver_flagged():
    raw = build_raw_tables(_sheets(
        [_cons_row(cons_rate=0.5)],
        prod_rows=[_prod_row(production_qty1=0.0)]))
    ws = rules.rule_nonpositive_driver(raw, CFG)
    assert len(ws) == 1


def test_clean_data_has_no_fatal():
    raw = build_raw_tables(_sheets([_cons_row()], prod_rows=[_prod_row()]))
    ws = rules.run_all(raw, CFG)
    assert not rules.has_fatal(ws)
