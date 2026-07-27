"""M5/M6 integration: the full pipeline on the sample workbook.

Definition-of-done checks: every one of the 820 series produces either a
forecast with stated confidence or an explicit reason why not; forecasts are
non-negative; the run finishes inside the 10-minute budget (N1).
"""
import json
import time
from pathlib import Path

import pandas as pd
import pytest

from core.config import EngineConfig
from core.pipeline import run_forecast
from core.store.repository import Repository

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_public.xlsx"

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "results.db"
    started = time.perf_counter()
    run_id = run_forecast(FIXTURE, EngineConfig(), db_path=db, run_name="ci")
    duration = time.perf_counter() - started
    return {"db": db, "run_id": run_id, "duration": duration}


def test_run_completes_inside_ten_minutes(run):
    assert run["duration"] < 600


def test_every_series_has_a_selection_with_reason_or_confidence(run):
    with Repository(run["db"]) as repo:
        sel = repo.get_selections(run["run_id"])
        series = repo.get_series()
    assert len(sel) == 820
    assert sel["confidence"].notna().all()
    for reason in sel["reason_text"]:
        payload = json.loads(reason)
        assert payload["reason_code"]
        assert payload["gate_reason"]
    assert set(sel["series_id"]) == set(series["series_id"])


def test_forecasts_nonnegative_and_intervals_ordered(run):
    with Repository(run["db"]) as repo:
        fc = repo.get_forecasts(run["run_id"])
    assert len(fc) == 820 * EngineConfig().forecast.horizon
    assert (fc["target_value"] >= 0).all()
    assert (fc["lower_95"] <= fc["lower_80"] + 1e-9).all()
    assert (fc["upper_80"] <= fc["upper_95"] + 1e-9).all()
    demand = fc["reconstructed_demand"].dropna()
    assert (demand >= 0).all()


def test_orphan_series_excluded_from_reconstruction_but_not_deleted(run):
    with Repository(run["db"]) as repo:
        fc = repo.get_forecasts(run["run_id"], ["code136|a|C"])
        series = repo.get_series()
    orphan = series[series["series_id"] == "code136|a|C"]
    assert len(orphan) == 1
    assert orphan.iloc[0]["mode"] == "relative"       # never flipped
    assert orphan.iloc[0]["is_orphan"] == 1
    assert len(fc) > 0                                # forecast exists (rate)
    assert fc["reconstructed_demand"].isna().all()    # demand never guessed


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
