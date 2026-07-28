"""Workbook read/write helpers for the UI.

Path resolution itself lives in ONE place — `core.paths`. This module only
re-exports those functions so existing UI code keeps working, and adds the
workbook-shaped helpers that are specific to the Data page.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.paths import (  # noqa: F401  (re-exported for the UI)
    DATA_DIR_ENVS,
    bundled_sample,
    cache_dir,
    data_dir,
    output_dir,
    resource_path,
    working_workbook,
)

#: kept for callers that referenced the old single-name constant
DATA_DIR_ENV = DATA_DIR_ENVS[-1]

SHEET_ORDER = ["bom", "consumption", "prod", "consumption_figs"]


def repo_root() -> Path:
    """Only meaningful in a source checkout; the bundle root when frozen."""
    from core.paths import bundle_root

    return bundle_root()


def default_input_path() -> Path | None:
    """What the app loads when the user has chosen nothing yet: their working
    copy if one exists, else the bundled default workbook."""
    working = working_workbook()
    if working.exists():
        return working
    return bundled_sample()


def read_workbook_sheets(path: Path) -> dict[str, pd.DataFrame]:
    """Read the input sheets with their EXTERNAL column names, for display
    and editing. Missing optional sheets come back as empty frames."""
    frames: dict[str, pd.DataFrame] = {}
    with pd.ExcelFile(path, engine="openpyxl") as xl:
        for sheet in SHEET_ORDER:
            frames[sheet] = xl.parse(sheet) if sheet in xl.sheet_names \
                else pd.DataFrame()
    return frames


def write_workbook(frames: dict[str, pd.DataFrame], path: Path) -> None:
    """Write the four input sheets to an xlsx at `path` (working copy)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet in SHEET_ORDER:
            if sheet in frames and frames[sheet] is not None:
                frames[sheet].to_excel(writer, sheet_name=sheet, index=False)
