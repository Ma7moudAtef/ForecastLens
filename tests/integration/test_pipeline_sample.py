"""M5/M6 integration: the full pipeline on the sample workbook.

Definition-of-done checks: every one of the 820 series produces either a
forecast with stated confidence or an explicit reason why not; forecasts are
non-negative; the run finishes inside the 10-minute budget (N1).
"""
import json
import time

import pandas as pd
import pytest

from core.config import EngineConfig
from core.store.repository import Repository

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def run(pipeline_run):
    return pipeline_run


def test_run_completes_inside_ten_minutes(run):
    assert run["duration"] < 600


def test_every_series_has_a_selection_with_reason_or_confidence(run):
    with Repository(run["db"]) as repo:
        sel = repo.get_selections(run["run_id"])
        series = repo.get_series()
    assert len(sel) == 820
    assert sel["confidence"].notna().all()
    assert sel["reason_code"].notna().all()
    for reason in sel["reason_text"]:
        assert isinstance(reason, str) and len(reason) > 30
        assert "MASE" not in reason           # plain language, no metric dumps
    assert set(sel["series_id"]) == set(series["series_id"])


def test_every_rejected_candidate_has_a_reason(run):
    with Repository(run["db"]) as repo:
        sel = repo.get_selections(run["run_id"])
    competed = sel[sel["route"] == "compete"]
    assert len(competed) > 300
    for rejected_json in competed["rejected_json"]:
        rejected = json.loads(rejected_json)
        assert len(rejected) >= 1
        for cand in rejected:
            assert cand["reason"] and len(cand["reason"]) > 15


def test_forecasts_nonnegative_and_intervals_ordered(run):
    with Repository(run["db"]) as repo:
        fc = repo.get_forecasts(run["run_id"])
    assert len(fc) == 820 * EngineConfig().forecast.horizon
    assert (fc["target_value"] >= 0).all()
    assert (fc["lower_95"] <= fc["lower_80"] + 1e-9).all()
    assert (fc["upper_80"] <= fc["upper_95"] + 1e-9).all()
    demand = fc["reconstructed_demand"].dropna()
    assert (demand >= 0).all()


def test_orphan_series_is_forecast_on_quantity_and_never_deleted(run):
    """Its rate has no denominator in any period, so the quantity is forecast
    directly — a usable answer where a rate against nothing is not. The
    series is still flagged, and nothing is guessed or removed."""
    with Repository(run["db"]) as repo:
        fc = repo.get_forecasts(run["run_id"], ["code136|a|C"])
        series = repo.get_series()
    orphan = series[series["series_id"] == "code136|a|C"]
    assert len(orphan) == 1
    assert orphan.iloc[0]["mode"] == "absolute"
    assert orphan.iloc[0]["mode_source"] == "no_driver"
    assert orphan.iloc[0]["is_orphan"] == 1
    assert len(fc) > 0
    # an Absolute forecast reconstructs demand from the calendar, not from a
    # driver plan, so a real quantity comes out and no denominator is invented
    assert fc["reconstructed_demand"].notna().all()
    assert (fc["reconstructed_demand"] >= 0).all()
    assert fc["driver_plan"].isna().all()


def test_routed_series_have_intermittent_family_winners(run):
    with Repository(run["db"]) as repo:
        sel = repo.get_selections(run["run_id"])
        series = repo.get_series()
    routed = series[series["pattern_class"].isin(["intermittent", "lumpy"])]
    merged = sel.merge(routed[["series_id"]], on="series_id")
    assert len(merged) == 235
    assert set(merged["model_name"]) <= {"SBA", "TSB", "Croston", "ZeroForecast"}


def test_cold_start_series_are_low_confidence(run):
    with Repository(run["db"]) as repo:
        sel = repo.get_selections(run["run_id"])
        series = repo.get_series()
    short = series[series["n_reliable"] < 6]
    merged = sel.merge(short[["series_id"]], on="series_id")
    assert (merged["confidence_label"] == "low").all()


def test_results_reload_quickly(run):
    started = time.perf_counter()
    with Repository(run["db"]) as repo:
        repo.get_selections(run["run_id"])
        repo.get_series()
        repo.get_forecasts(run["run_id"])
    assert time.perf_counter() - started < 2.0        # N2


def test_run_metadata_recorded(run):
    with Repository(run["db"]) as repo:
        runs = repo.list_runs()
    row = runs[runs["run_id"] == run["run_id"]].iloc[0]
    assert row["status"] == "complete"
    assert row["n_series"] == 820
