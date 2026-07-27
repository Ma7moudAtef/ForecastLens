"""M1 integration: the sample workbook loads and validation reproduces the
known data characteristics."""
from pathlib import Path

import pytest

from core.config import EngineConfig
from core.io.excel_source import ExcelSource
from core.store.repository import Repository
from core.validate import rules

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_public.xlsx"


@pytest.fixture(scope="module")
def raw():
    return ExcelSource(FIXTURE).load()


@pytest.fixture(scope="module")
def warnings(raw):
    return rules.run_all(raw, EngineConfig())


def test_shapes(raw):
    assert len(raw.consumption) == 14194
    assert raw.consumption["item_code"].nunique() == 248
    assert len(raw.items) == 138
    assert len(raw.driver) == 2316
    assert len(raw.standard_rates) == 552


def test_no_production_column_survives(raw):
    for df in (raw.items, raw.consumption, raw.driver, raw.standard_rates):
        assert not any("prod" in c.lower() for c in df.columns)


def test_exactly_one_orphan_series_detected(warnings):
    orphans = [w for w in warnings if w.code == "ORPHAN_SERIES"]
    assert len(orphans) == 1
    w = orphans[0]
    assert (w.item_code, w.line, w.output_type) == ("code136", "a", "C")
    assert "denominator does not exist" in w.message


def test_zero_partial_orphans(warnings):
    assert [w for w in warnings if w.code == "MISSING_DRIVER_PERIODS"] == []


def test_zero_mixed_mode_series(warnings):
    assert [w for w in warnings if w.code == "MIXED_MODE_SERIES"] == []


def test_duplicates_flagged(warnings):
    dups = [w for w in warnings if w.code == "DUPLICATE_PERIOD_ROWS"]
    assert len(dups) > 0
    assert sum(w.count for w in dups) == 553  # duplicated (series, period) groups


def test_items_missing_from_bom(warnings):
    ws = [w for w in warnings if w.code == "ITEM_NOT_IN_BOM"]
    assert len(ws) == 1
    assert ws[0].count == 121  # every Absolute item is absent from bom


def test_insufficient_history_count(warnings):
    ws = [w for w in warnings if w.code == "INSUFFICIENT_HISTORY"]
    assert len(ws) == 1
    assert ws[0].count == 304


def test_no_fatal_on_sample(warnings):
    assert not rules.has_fatal(warnings)


def test_repository_round_trip(tmp_path, raw):
    db = tmp_path / "t.db"
    with Repository(db) as repo:
        items = raw.items.drop_duplicates("item_code")
        driver = raw.driver.copy()
        driver["period"] = driver["date"].astype(str)
        driver = driver[["period", "line", "output_type", "driver_qty",
                         "driver_uom", "driver_type"]]
        # plan rows are daily → aggregate to (period,line,output,type) later;
        # here just check writes are parameterized and readable
        driver = driver.drop_duplicates(["period", "line", "output_type",
                                         "driver_type"])
        repo.replace_reference_data(items, driver, raw.standard_rates)
        assert len(repo.get_items()) == 138
        assert len(repo.get_standard_rates()) == 552
        assert repo.get_driver("actual")["driver_qty"].min() > 0
