"""Data-file locations: the bundled default workbook and the user's editable
working copy. The bundled sample is read-only; edits always land in the
working copy."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

DATA_DIR_ENV = "FORECASTLENS_DATA_DIR"
SHEET_ORDER = ["bom", "consumption", "prod", "consumption_figs"]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bundled_sample() -> Path | None:
    """The default workbook shipped with the app (default_input_public)."""
    candidates = [
        repo_root() / "tests" / "fixtures" / "sample_public.xlsx",
    ]
    if hasattr(sys, "_MEIPASS"):
        candidates.insert(0, Path(sys._MEIPASS) / "data" / "sample_public.xlsx")
    for c in candidates:
        if c.exists():
            return c
    return None


def data_dir() -> Path:
    base = os.environ.get(DATA_DIR_ENV)
    if base:
        p = Path(base)
    elif os.name == "nt":
        p = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ForecastLens"
    else:
        p = Path.home() / ".forecastlens"
    p.mkdir(parents=True, exist_ok=True)
    return p


def working_workbook() -> Path:
    """The editable copy of the input data. Created on first save."""
    return data_dir() / "working_input.xlsx"


def default_input_path() -> Path | None:
    """What the app loads when the user has chosen nothing yet: their working
    copy if one exists, else the bundled default workbook."""
    w = working_workbook()
    if w.exists():
        return w
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
