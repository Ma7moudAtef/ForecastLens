import pandas as pd
import pytest

from core.io.schema import RawTables, SchemaError, build_raw_tables


def _minimal_sheets(with_driver=True, with_mode_col=False):
    bom = pd.DataFrame({
        "item_code": ["A1"], "item_description": ["widget"], "uom": ["p"],
        "unit_price_$": [1.0], "unit_wt_kg": [0.1],
        "category_level1": ["c1"], "category_level2": ["c2"],
        "category_level3": ["c3"],
    })
    if with_mode_col:
        bom["mode"] = ["relative"]
    cons = pd.DataFrame({
        "date": ["2024-01-01"], "item_code": ["A1"],
        "cons_qty_base_uom": [10.0], "cons_qty_ton": [0.5], "cons_$": [100.0],
        "output_type": ["x"], "production_line": ["a"],
        "cons_rate": [0.01], "cons_rate_uom": ["p/t"],
    })
    sheets = {"bom": bom, "consumption": cons}
    if with_driver:
        sheets["prod"] = pd.DataFrame({
            "date": ["2024-01-01"], "production_uom1": ["t"],
            "production_qty1": [1000.0], "production_uom2": ["s"],
            "production_qty2": [50.0], "output_type": ["x"],
            "production_line": ["a"], "production_type": ["actual"],
        })
    return sheets


def test_production_words_never_survive_the_boundary():
    raw = build_raw_tables(_minimal_sheets())
    for df in (raw.items, raw.consumption, raw.driver, raw.standard_rates):
        assert not any("production" in c or "prod" in c for c in df.columns), \
            list(df.columns)
    assert "driver_qty" in raw.driver.columns
    assert raw.driver.loc[0, "driver_qty"] == 1000.0
    assert raw.driver.loc[0, "driver_type"] == "actual"


def test_driverless_workbook_is_legitimate():
    """Trading / e-commerce shape: no prod sheet at all."""
    raw = build_raw_tables(_minimal_sheets(with_driver=False))
    assert isinstance(raw.driver, pd.DataFrame)
    assert raw.driver.empty
    assert "driver_qty" in raw.driver.columns


def test_missing_required_sheet_is_fatal():
    sheets = _minimal_sheets()
    del sheets["consumption"]
    with pytest.raises(SchemaError, match="consumption"):
        build_raw_tables(sheets)


def test_missing_required_column_is_fatal():
    sheets = _minimal_sheets()
    sheets["consumption"] = sheets["consumption"].drop(columns=["cons_rate"])
    with pytest.raises(SchemaError, match="cons_rate"):
        build_raw_tables(sheets)


def test_optional_declared_mode_column():
    raw = build_raw_tables(_minimal_sheets(with_mode_col=True))
    assert raw.items.loc[0, "declared_mode"] == "relative"
    raw2 = build_raw_tables(_minimal_sheets(with_mode_col=False))
    assert raw2.items["declared_mode"].isna().all()


def test_dtype_coercion_records_failures():
    sheets = _minimal_sheets()
    cons = sheets["consumption"]
    cons["cons_qty_base_uom"] = cons["cons_qty_base_uom"].astype(object)
    cons.loc[0, "cons_qty_base_uom"] = "not-a-number"
    raw = build_raw_tables(sheets)
    assert raw.coercion_failures.get("consumption.qty_base") == 1
    assert pd.isna(raw.consumption.loc[0, "qty_base"])
