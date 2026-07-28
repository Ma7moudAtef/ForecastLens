"""Export a run's results.

Lives in core, not in the UI, so the web app, the CLI and the frozen exe all
produce byte-identical files from the same code — the Portfolio page and
`ForecastEngine --export` call straight into here.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core import identity
from core.paths import output_dir
from core.store.repository import Repository

SHEETS = ("forecasts", "selections", "series", "context", "warnings")


def build_frames(db_path: str | Path, run_id: str | None = None,
                 series_ids: set[str] | None = None,
                 sheets: tuple[str, ...] = SHEETS) -> dict[str, pd.DataFrame]:
    """The exported tables, each carrying item code, description, line and
    output type as separate columns (never the internal series identifier)."""
    with Repository(db_path) as repo:
        run_id = run_id or repo.latest_complete_run_id()
        if run_id is None:
            return {}
        series = repo.get_series()
        items = repo.get_items()
        forecasts = repo.get_forecasts(run_id)
        selections = repo.get_selections(run_id)
        warnings = repo.get_warnings(run_id)
        context = repo.get_series_context()

    lookup = identity.description_lookup(items)
    scoped = series if series_ids is None else \
        series[series["series_id"].isin(series_ids)]
    keep = set(scoped["series_id"])

    frames: dict[str, pd.DataFrame] = {}
    if "forecasts" in sheets:
        frames["forecasts"] = identity.add_identity(
            forecasts[forecasts["series_id"].isin(keep)], series, items)
    if "selections" in sheets:
        frames["selections"] = identity.add_identity(
            selections[selections["series_id"].isin(keep)]
            .drop(columns=["rejected_json"], errors="ignore"), series, items)
    if "series" in sheets:
        out = scoped.copy()
        out.insert(1, "description",
                   out["item_code"].map(lambda c: lookup.get(str(c), "")))
        frames["series"] = out.drop(columns=["series_id"])
    if "context" in sheets and not context.empty:
        # the operating-context finding for every exported series, including
        # the ones where the answer was "it makes no difference here"
        frames["context"] = identity.add_identity(
            context[context["series_id"].isin(keep)]
            .drop(columns=["regime_counts_json"], errors="ignore"),
            series, items)
    if "warnings" in sheets:
        frames["warnings"] = identity.expand_series_id(warnings, lookup)
    return frames


def write_workbook(frames: dict[str, pd.DataFrame], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for name, frame in frames.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
    return out_path


def export_workbook(db_path: str | Path, run_id: str | None = None,
                    out_path: Path | None = None,
                    series_ids: set[str] | None = None) -> Path:
    """Build and write an Excel export. Returns the file written."""
    frames = build_frames(db_path, run_id, series_ids)
    if not frames:
        raise RuntimeError("nothing to export: no completed run in "
                           f"{db_path}")
    target = out_path or (output_dir() / "forecastengine_export.xlsx")
    return write_workbook(frames, Path(target))
