"""Shared fixtures: one full pipeline run per test session, reused by the
pipeline assertions and the UI smoke tests."""
import time
from pathlib import Path

import pytest

from core.config import EngineConfig
from core.pipeline import run_forecast

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_public.xlsx"


@pytest.fixture(scope="session")
def pipeline_run(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "results.db"
    started = time.perf_counter()
    run_id = run_forecast(FIXTURE, EngineConfig(), db_path=db, run_name="ci")
    duration = time.perf_counter() - started
    return {"db": db, "run_id": run_id, "duration": duration}
