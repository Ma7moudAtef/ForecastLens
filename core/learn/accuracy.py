"""Continuous learning: compare stored forecasts with newly imported actuals.

On each actuals import: stored forecast vs actual per period, error recorded
into accuracy_history, drift detected (recent error well above earlier
error), and drifting series flagged for re-evaluation via a warning row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from core.config import EngineConfig
from core.io.excel_source import ExcelSource
from core.prep.calendar import to_period_index
from core.store.repository import Repository, series_id_of
from core.validate.rules import Severity, ValidationWarning

DRIFT_FACTOR = 1.5


@dataclass
class ImportResult:
    n_matched: int
    n_series: int
    n_drift: int
    drifting_series: list[str]


def _actual_targets(path: str | Path, cfg: EngineConfig) -> pd.DataFrame:
    """Actual demand per (series_id, period): quantity for absolute-style
    comparison — we compare on RECONSTRUCTED demand scale, which is qty."""
    raw = ExcelSource(path).load()
    cons = raw.consumption.copy()
    cons["period"] = to_period_index(cons["date"], cfg.granularity).astype(str)
    grouped = (cons.groupby(["item_code", "line", "output_type", "period"],
                            dropna=False)
               .agg(qty=("qty_base", "sum")).reset_index())
    grouped["series_id"] = [
        series_id_of(r.item_code,
                     None if pd.isna(r.line) else r.line,
                     None if pd.isna(r.output_type) else r.output_type)
        for r in grouped.itertuples()]
    return grouped[["series_id", "period", "qty"]]


def import_actuals(path: str | Path, db_path: str | Path,
                   run_id: str, cfg: EngineConfig | None = None) -> ImportResult:
    """Compare run `run_id`'s stored forecasts against actuals found in the
    workbook at `path`. Records accuracy_history and drift warnings."""
    cfg = cfg or EngineConfig()
    actuals = _actual_targets(path, cfg)

    with Repository(db_path) as repo:
        fc = repo.get_forecasts(run_id)
        sel = repo.get_selections(run_id)
        model_by_series = sel.set_index("series_id")["model_name"].to_dict()

        merged = fc.merge(actuals, on=["series_id", "period"], how="inner")
        # compare on the demand scale where reconstruction exists, else on
        # the target scale is meaningless against qty — skip those rows
        merged = merged.dropna(subset=["reconstructed_demand"])
        if merged.empty:
            return ImportResult(0, 0, 0, [])

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = pd.DataFrame({
            "series_id": merged["series_id"],
            "period": merged["period"],
            "forecast_value": merged["reconstructed_demand"],
            "actual_value": merged["qty"],
            "error": merged["reconstructed_demand"] - merged["qty"],
            "abs_pct_error": np.where(
                merged["qty"] != 0,
                (merged["reconstructed_demand"] - merged["qty"]).abs()
                / merged["qty"].abs() * 100, np.nan),
            "model_name": merged["series_id"].map(model_by_series),
            "run_id": run_id,
            "recorded_at": now,
        })
        repo.write_accuracy(rows)

        # drift detection over the full accumulated history
        history = repo.get_accuracy()
        drifting = []
        for sid, g in history.dropna(subset=["actual_value"]).groupby("series_id"):
            errs = g.sort_values("period")["abs_pct_error"].dropna()
            if len(errs) >= 4:
                half = len(errs) // 2
                early, late = errs.iloc[:half].mean(), errs.iloc[half:].mean()
                if late > DRIFT_FACTOR * max(early, 1e-9):
                    drifting.append(sid)
        if drifting:
            wdf = pd.DataFrame([{
                "series_id": sid, "code": "ACCURACY_DRIFT",
                "severity": Severity.WARNING.value, "count": 1,
                "message": ("Forecast error is rising: recent error is more "
                            f"than {DRIFT_FACTOR}x the earlier level. "
                            "Re-evaluate this series (behaviour may have "
                            "changed).")} for sid in drifting])
            repo.write_warnings(run_id, wdf)

        return ImportResult(
            n_matched=len(rows),
            n_series=rows["series_id"].nunique(),
            n_drift=len(drifting),
            drifting_series=drifting)
