"""M9: importing actuals updates accuracy history and detects drift.

Workbooks are generated at test time in tmp_path — never committed (the data
guard forbids spreadsheets outside the whitelisted sample).
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.config import EngineConfig
from core.learn.accuracy import import_actuals
from core.pipeline import run_forecast
from core.store.repository import Repository

pytestmark = pytest.mark.slow


def _write_workbook(path: Path, months: int, per_day: float = 2.0) -> None:
    """A driver-less (trading-shape) workbook: one absolute item with
    constant per-day demand over `months` months from Jan 2024."""
    dates = pd.date_range("2024-01-01", periods=months, freq="MS")
    cons = pd.DataFrame({
        "date": dates,
        "item_code": "T1",
        "cons_qty_base_uom": [per_day * d.days_in_month for d in dates],
        "cons_qty_ton": 0.0, "cons_$": 1.0,
        "output_type": "retail", "production_line": "web",
        "cons_rate": None, "cons_rate_uom": None,
    })
    bom = pd.DataFrame([{
        "item_code": "T1", "item_description": "widget", "uom": "p",
        "unit_price_$": 9.99, "unit_wt_kg": 0.2, "category_level1": "c1",
        "category_level2": "c2", "category_level3": "c3"}])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        bom.to_excel(writer, sheet_name="bom", index=False)
        cons.to_excel(writer, sheet_name="consumption", index=False)


def test_actuals_import_updates_accuracy_history(tmp_path):
    history = tmp_path / "history.xlsx"
    actuals = tmp_path / "actuals.xlsx"
    db = tmp_path / "r.db"
    _write_workbook(history, months=24)
    _write_workbook(actuals, months=30)      # six months newer

    cfg = EngineConfig(forecast={"horizon": 6})
    run_id = run_forecast(history, cfg, db_path=db, run_name="learn-test")

    result = import_actuals(actuals, db, run_id, cfg)
    assert result.n_matched == 6             # all six forecast months matched
    assert result.n_series == 1

    with Repository(db) as repo:
        acc = repo.get_accuracy()
    assert len(acc) == 6
    assert acc["actual_value"].notna().all()
    assert acc["error"].notna().all()
    assert acc["model_name"].notna().all()
    # constant per-day series: the forecast should be close to the truth
    assert (acc["abs_pct_error"] < 15).all()


def test_reimport_is_idempotent(tmp_path):
    history = tmp_path / "history.xlsx"
    actuals = tmp_path / "actuals.xlsx"
    db = tmp_path / "r.db"
    _write_workbook(history, months=24)
    _write_workbook(actuals, months=30)
    cfg = EngineConfig(forecast={"horizon": 6})
    run_id = run_forecast(history, cfg, db_path=db)

    import_actuals(actuals, db, run_id, cfg)
    import_actuals(actuals, db, run_id, cfg)  # upsert, not duplicate
    with Repository(db) as repo:
        assert len(repo.get_accuracy()) == 6


def test_driverless_dataset_full_pipeline_zero_code_changes(tmp_path):
    """Definition of done #8: a trading/e-commerce shaped dataset (no prod
    sheet at all) runs the whole pipeline unmodified."""
    wb = tmp_path / "trading.xlsx"
    db = tmp_path / "r.db"
    _write_workbook(wb, months=18)
    run_id = run_forecast(wb, EngineConfig(), db_path=db)
    with Repository(db) as repo:
        series = repo.get_series()
        fc = repo.get_forecasts(run_id)
    assert (series["mode"] == "absolute").all()
    assert (series["is_orphan"] == 0).all()
    assert len(fc) > 0
    assert fc["reconstructed_demand"].notna().all()  # per-day × days
