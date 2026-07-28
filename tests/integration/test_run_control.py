"""Aborting a run, and the verbose progress log."""
from pathlib import Path

import pandas as pd
import pytest

from core.config import EngineConfig
from core.pipeline import RunCancelled, run_forecast
from core.store.repository import Repository

pytestmark = pytest.mark.slow

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_public.xlsx"


def _one_item() -> str:
    bom = pd.read_excel(FIXTURE, sheet_name="bom", engine="openpyxl")
    cons = pd.read_excel(FIXTURE, sheet_name="consumption", engine="openpyxl")
    return next(c for c in bom["item_code"] if c in set(cons["item_code"]))


def _scoped_cfg() -> EngineConfig:
    return EngineConfig(scope={"item_codes": [_one_item()]},
                        forecast={"horizon": 3})


def test_cancelling_before_fitting_stops_the_run(tmp_path):
    db = tmp_path / "r.db"
    with pytest.raises(RunCancelled):
        run_forecast(FIXTURE, _scoped_cfg(), db_path=db,
                     cancel_cb=lambda: True)

    with Repository(db) as repo:
        assert repo.list_runs().empty      # no partial run left behind
        assert repo.latest_complete_run_id() is None


def test_cancelling_midway_discards_partial_results(tmp_path):
    """Cancel once fitting has started: nothing half-finished survives."""
    db = tmp_path / "r.db"
    seen: list[str] = []

    def cancel_after_fitting_starts() -> bool:
        return any("Competing models" in line for line in seen)

    with pytest.raises(RunCancelled):
        run_forecast(FIXTURE, EngineConfig(forecast={"horizon": 3}),
                     db_path=db, log_cb=seen.append,
                     cancel_cb=cancel_after_fitting_starts)

    assert any("Competing models" in line for line in seen)
    assert any("Cancelled" in line for line in seen)
    with Repository(db) as repo:
        assert repo.list_runs().empty
        assert repo.get_forecasts("").empty


def test_cancellation_does_not_disturb_earlier_runs(tmp_path):
    db = tmp_path / "r.db"
    good = run_forecast(FIXTURE, _scoped_cfg(), db_path=db, run_name="keeper")

    with pytest.raises(RunCancelled):
        run_forecast(FIXTURE, _scoped_cfg(), db_path=db,
                     cancel_cb=lambda: True)

    with Repository(db) as repo:
        runs = repo.list_runs()
        assert list(runs["run_id"]) == [good]
        assert not repo.get_selections(good).empty


def test_a_run_that_is_never_cancelled_completes(tmp_path):
    db = tmp_path / "r.db"
    run_id = run_forecast(FIXTURE, _scoped_cfg(), db_path=db,
                          cancel_cb=lambda: False)
    with Repository(db) as repo:
        assert repo.latest_complete_run_id() == run_id


def test_log_is_verbose_and_covers_every_stage(tmp_path):
    db = tmp_path / "r.db"
    lines: list[str] = []
    run_forecast(FIXTURE, _scoped_cfg(), db_path=db, log_cb=lines.append)

    text = "\n".join(lines).lower()
    for stage in ["reading workbook", "validating", "building the forecast",
                  "studying each series", "scope", "competing models",
                  "saving", "run finished"]:
        assert stage in text, f"missing stage in log: {stage}\n{text}"

    # counts and timings, not just stage names
    assert any("consumption rows" in line for line in lines)
    assert any("relative" in line and "absolute" in line for line in lines)
    assert any("demand patterns" in line.lower() for line in lines)
    assert any("models chosen" in line.lower() for line in lines)
    assert len(lines) >= 10


def test_log_reports_chunk_progress_on_a_full_run(tmp_path):
    """Progress must be visible while the long stage is running, not only
    when it finishes."""
    db = tmp_path / "r.db"
    lines: list[str] = []
    stages: list[tuple[str, float]] = []
    run_forecast(FIXTURE, EngineConfig(forecast={"horizon": 3}), db_path=db,
                 log_cb=lines.append,
                 progress_cb=lambda s, f: stages.append((s, f)))

    chunk_lines = [l for l in lines if "series done" in l]
    assert len(chunk_lines) >= 5, chunk_lines
    assert any("left" in l for l in chunk_lines)      # eta reported

    forecasting = [s for s, _ in stages if s.startswith("forecasting ")]
    assert len(forecasting) >= 5
    fractions = [f for _, f in stages]
    assert fractions == sorted(fractions)             # monotonic progress
