#!/usr/bin/env python3
"""Regenerate the golden regression snapshot from the sample workbook.

Any change to selections or forecasts must be an intentional, reviewed diff
of tests/fixtures/golden_selections.csv and golden_summary.json.

    python scripts/update_golden.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURE = ROOT / "tests" / "fixtures" / "sample_public.xlsx"
GOLDEN_CSV = ROOT / "tests" / "fixtures" / "golden_selections.csv"
GOLDEN_JSON = ROOT / "tests" / "fixtures" / "golden_summary.json"


def snapshot(db_path, run_id):
    import pandas as pd

    from core.store.repository import Repository

    with Repository(db_path) as repo:
        sel = repo.get_selections(run_id)
        fc = repo.get_forecasts(run_id)
        series = repo.get_series()

    golden = sel[["series_id", "model_name", "window", "route", "reason_code",
                  "confidence_label"]].copy()
    golden["mase"] = sel["mase"].round(4)
    golden = golden.sort_values("series_id").reset_index(drop=True)

    merged = fc.merge(series[["series_id", "mode"]], on="series_id")
    summary = {
        "n_series": int(len(series)),
        "n_forecast_rows": int(len(fc)),
        "demand_total_by_mode": {
            mode: round(float(g["reconstructed_demand"].sum()), 2)
            for mode, g in merged.groupby("mode")},
        "winner_counts": sel["model_name"].value_counts().to_dict(),
    }
    return golden, summary


def main() -> None:
    from core.config import EngineConfig
    from core.pipeline import run_forecast

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "golden.db"
        run_id = run_forecast(FIXTURE, EngineConfig(), db_path=db,
                              run_name="golden")
        golden, summary = snapshot(db, run_id)
    golden.to_csv(GOLDEN_CSV, index=False)
    GOLDEN_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote {GOLDEN_CSV.name} ({len(golden)} rows) and {GOLDEN_JSON.name}")


if __name__ == "__main__":
    main()
