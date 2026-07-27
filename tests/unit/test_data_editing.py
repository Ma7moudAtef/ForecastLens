"""Extend/replace semantics and the workbook edit round-trip.

Working copies are written to a tmp path — never into the repository (the
data guard forbids spreadsheets outside the whitelisted sample)."""
import pandas as pd
import pytest

from app.components import paths
from app.components.tables import ImportMode, apply_import, unknown_columns

CURRENT = pd.DataFrame({"item_code": ["a", "b"], "qty": [1.0, 2.0]})
INCOMING = pd.DataFrame({"item_code": ["c"], "qty": [3.0]})


def test_extend_appends_rows_and_keeps_existing():
    out = apply_import(CURRENT, INCOMING, ImportMode.EXTEND)
    assert len(out) == 3
    assert list(out["item_code"]) == ["a", "b", "c"]
    assert len(CURRENT) == 2  # input untouched


def test_replace_discards_existing_rows():
    out = apply_import(CURRENT, INCOMING, ImportMode.REPLACE)
    assert len(out) == 1
    assert list(out["item_code"]) == ["c"]


def test_extend_aligns_columns_and_reports_unknown_ones():
    incoming = pd.DataFrame({"item_code": ["c"], "qty": [3.0],
                             "surprise": ["x"]})
    assert unknown_columns(CURRENT, incoming) == ["surprise"]
    out = apply_import(CURRENT, incoming, ImportMode.EXTEND)
    assert list(out.columns) == ["item_code", "qty"]   # schema preserved
    assert len(out) == 3


def test_extend_fills_missing_columns_as_empty():
    incoming = pd.DataFrame({"item_code": ["c"]})       # no qty
    out = apply_import(CURRENT, incoming, ImportMode.EXTEND)
    assert pd.isna(out.iloc[-1]["qty"])


def test_extend_into_empty_table_behaves_as_replace():
    out = apply_import(pd.DataFrame(), INCOMING, ImportMode.EXTEND)
    assert len(out) == 1


def test_workbook_round_trip_preserves_sheets(tmp_path):
    frames = {
        "bom": pd.DataFrame({"item_code": ["a"], "item_description": ["W"]}),
        "consumption": pd.DataFrame({"date": ["2024-01-01"],
                                     "item_code": ["a"]}),
        "prod": pd.DataFrame({"date": ["2024-01-01"], "production_qty1": [5.0]}),
        "consumption_figs": pd.DataFrame({"item_code": ["a"],
                                          "std_cons_rate": [0.5]}),
    }
    target = tmp_path / "working.xlsx"
    paths.write_workbook(frames, target)
    assert target.exists()

    back = paths.read_workbook_sheets(target)
    assert set(back) == set(paths.SHEET_ORDER)
    assert back["bom"].iloc[0]["item_description"] == "W"
    assert back["prod"].iloc[0]["production_qty1"] == 5.0


def test_edited_workbook_is_loadable_by_the_engine(tmp_path):
    """An edit saved from the Data page must still be a valid engine input."""
    from core.io.excel_source import ExcelSource

    source = paths.bundled_sample()
    assert source is not None
    frames = paths.read_workbook_sheets(source)
    frames["bom"] = frames["bom"].head(20)          # simulate an edit
    target = tmp_path / "working.xlsx"
    paths.write_workbook(frames, target)

    raw = ExcelSource(target).load()
    assert len(raw.items) == 20
    assert not raw.consumption.empty


def test_default_input_prefers_working_copy(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    assert paths.default_input_path() == paths.bundled_sample()
    paths.write_workbook({"bom": pd.DataFrame({"item_code": ["a"]})},
                         paths.working_workbook())
    assert paths.default_input_path() == paths.working_workbook()


def test_bundled_sample_is_the_public_workbook():
    sample = paths.bundled_sample()
    assert sample is not None and sample.exists()
    assert sample.name == "sample_public.xlsx"
