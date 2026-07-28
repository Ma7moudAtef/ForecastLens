"""The assertions both the source version and the frozen exe must satisfy.

Written once, imported by both parity tests. Anything that only passes in
one of them is exactly the divergence this suite exists to catch.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.store.repository import Repository

#: reference facts for tests/fixtures/sample_public.xlsx
EXPECTED_SERIES = 820
EXPECTED_ABSOLUTE_ITEMS = 121
EXPECTED_RELATIVE_ITEMS = 127
EXPECTED_ORPHANS = 1
ORPHAN_SERIES_ID = "code136|a|C"

#: forecast values are compared at this precision — tight enough that a
#: different BLAS path or model selection shows up, loose enough to survive
#: float formatting through SQLite
FORECAST_DECIMALS = 10


def assert_series_built(db_path: Path) -> pd.DataFrame:
    with Repository(db_path) as repo:
        series = repo.get_series()
    assert len(series) == EXPECTED_SERIES, \
        f"expected {EXPECTED_SERIES} series, got {len(series)}"
    return series


def assert_mode_split(series: pd.DataFrame) -> None:
    per_item = series.groupby("item_code")["mode"].first()
    absolute = int((per_item == "absolute").sum())
    relative = int((per_item == "relative").sum())
    assert absolute == EXPECTED_ABSOLUTE_ITEMS, absolute
    assert relative == EXPECTED_RELATIVE_ITEMS, relative
    assert series.groupby("item_code")["mode"].nunique().eq(1).all(), \
        "an item mixes modes"


def assert_orphans(series: pd.DataFrame) -> None:
    orphans = series[series["is_orphan"] == 1]
    assert len(orphans) == EXPECTED_ORPHANS, len(orphans)
    assert orphans.iloc[0]["series_id"] == ORPHAN_SERIES_ID
    assert orphans.iloc[0]["mode"] == "relative"


def assert_run_completed(db_path: Path, run_id: str) -> pd.DataFrame:
    with Repository(db_path) as repo:
        runs = repo.list_runs()
        selections = repo.get_selections(run_id)
        forecasts = repo.get_forecasts(run_id)
    row = runs[runs["run_id"] == run_id]
    assert not row.empty, f"run {run_id} missing from the database"
    assert row.iloc[0]["status"] == "complete"
    assert len(selections) == EXPECTED_SERIES
    assert not forecasts.empty
    assert (forecasts["target_value"] >= 0).all(), "negative forecast"
    return forecasts


def assert_database_round_trip(db_path: Path) -> None:
    """Written and readable — the check that fails when the database landed
    somewhere read-only inside the bundle."""
    assert Path(db_path).exists(), f"no database at {db_path}"
    assert Path(db_path).stat().st_size > 0
    with Repository(db_path) as repo:
        assert repo.latest_complete_run_id() is not None
        assert not repo.get_series().empty
        assert not repo.get_observations().empty


def assert_export_written(path: Path) -> None:
    assert path.exists(), f"no export written at {path}"
    assert path.stat().st_size > 0
    with pd.ExcelFile(path, engine="openpyxl") as xl:
        assert "forecasts" in xl.sheet_names, xl.sheet_names
        forecasts = xl.parse("forecasts")
    assert not forecasts.empty
    for column in ("item_code", "description", "line", "output_type"):
        assert column in forecasts.columns, forecasts.columns.tolist()
    assert "series_id" not in forecasts.columns


def forecast_fingerprint(db_path: Path, run_id: str) -> pd.DataFrame:
    """The comparable forecast table: sorted, rounded, index-free.

    Run ids differ between two runs by construction, so they are excluded —
    everything that describes the *numbers* is kept.
    """
    with Repository(db_path) as repo:
        forecasts = repo.get_forecasts(run_id)
        selections = repo.get_selections(run_id)

    numbers = forecasts.drop(columns=["run_id"], errors="ignore")
    numbers = numbers.sort_values(["series_id", "period"]).reset_index(drop=True)
    for column in numbers.select_dtypes("number").columns:
        numbers[column] = numbers[column].round(FORECAST_DECIMALS)

    chosen = selections[["series_id", "model_name", "window", "mase"]].copy()
    chosen["mase"] = chosen["mase"].round(FORECAST_DECIMALS)
    chosen = chosen.sort_values("series_id").reset_index(drop=True)
    return numbers.merge(chosen, on="series_id", how="left")


def assert_identical_forecasts(left: pd.DataFrame, right: pd.DataFrame,
                               left_name: str = "source",
                               right_name: str = "exe") -> None:
    """Byte-identical numbers — the check that proves the exe is not quietly
    taking a different code path."""
    assert list(left.columns) == list(right.columns), (
        f"{left_name} and {right_name} produced different columns:\n"
        f"  {left_name}: {list(left.columns)}\n  {right_name}: {list(right.columns)}")
    assert len(left) == len(right), (
        f"{left_name} produced {len(left)} forecast rows, "
        f"{right_name} produced {len(right)}")

    mismatched = []
    for column in left.columns:
        a, b = left[column], right[column]
        if a.equals(b):
            continue
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            diff = (a - b).abs()
            worst = float(diff.max(skipna=True) or 0.0)
            if worst == 0.0 and a.isna().equals(b.isna()):
                continue
            mismatched.append(f"{column}: max |difference| {worst:.3g}")
        else:
            n = int((a.astype(str) != b.astype(str)).sum())
            mismatched.append(f"{column}: {n} row(s) differ")
    assert not mismatched, (
        f"{left_name} and {right_name} disagree — the packaged build is "
        "taking a different code path:\n  " + "\n  ".join(mismatched))
