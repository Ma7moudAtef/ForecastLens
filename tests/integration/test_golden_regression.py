"""Golden-file regression: the sample workbook's selections are snapshotted.

Any change here must be an intentional, reviewed diff — regenerate with
`python scripts/update_golden.py` and review what moved and why.

Model choices are compared exactly. MASE is compared loosely (2 decimals)
to tolerate BLAS-level float differences across platforms without letting a
real selection change slip through.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from core.store.repository import Repository

pytestmark = pytest.mark.slow

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN_CSV = FIXTURES / "golden_selections.csv"
GOLDEN_JSON = FIXTURES / "golden_summary.json"


@pytest.fixture(scope="module")
def current(pipeline_run):
    with Repository(pipeline_run["db"]) as repo:
        sel = repo.get_selections(pipeline_run["run_id"])
        fc = repo.get_forecasts(pipeline_run["run_id"])
    return sel.sort_values("series_id").reset_index(drop=True), fc


def test_selection_choices_match_golden(current):
    sel, _ = current
    golden = pd.read_csv(GOLDEN_CSV, dtype={"window": "Int64"})
    now = sel[["series_id", "model_name", "window", "route",
               "reason_code", "confidence_label"]].copy()
    now["window"] = now["window"].astype("Int64")
    g = golden.drop(columns=["mase"]).reset_index(drop=True)
    diff = g.merge(now, on="series_id", suffixes=("_golden", "_now"))
    changed = diff[
        (diff["model_name_golden"] != diff["model_name_now"])
        | (diff["window_golden"].fillna(-1) != diff["window_now"].fillna(-1))
        | (diff["route_golden"] != diff["route_now"])]
    assert changed.empty, (
        f"{len(changed)} series changed selection vs golden — if intentional, "
        f"run scripts/update_golden.py and review the diff:\n"
        f"{changed.head(10).to_string()}")


def test_mase_within_tolerance_of_golden(current):
    sel, _ = current
    golden = pd.read_csv(GOLDEN_CSV)
    merged = golden[["series_id", "mase"]].merge(
        sel[["series_id", "mase"]], on="series_id",
        suffixes=("_golden", "_now"))
    both = merged.dropna()
    assert ((both["mase_golden"] - both["mase_now"]).abs() < 0.01).all()


def test_summary_matches_golden(current):
    sel, fc = current
    golden = json.loads(GOLDEN_JSON.read_text())
    assert len(sel) == golden["n_series"]
    assert len(fc) == golden["n_forecast_rows"]
    assert sel["model_name"].value_counts().to_dict() == golden["winner_counts"]
