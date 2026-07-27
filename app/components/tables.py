"""Table editing semantics for the Data page.

Two ways to bring rows into an existing sheet:
  EXTEND  — append the incoming rows to what is already there
  REPLACE — discard the current rows and use the incoming ones instead
"""
from __future__ import annotations

from enum import Enum

import pandas as pd


class ImportMode(str, Enum):
    EXTEND = "extend"
    REPLACE = "replace"


def apply_import(current: pd.DataFrame, incoming: pd.DataFrame,
                 mode: ImportMode) -> pd.DataFrame:
    """Combine `incoming` into `current` per `mode`.

    On EXTEND the incoming frame is aligned to the current table's columns:
    unknown columns are dropped and absent ones become empty, so the sheet
    keeps a stable schema. REPLACE takes the incoming frame as-is.
    """
    if mode is ImportMode.REPLACE or current is None or current.empty:
        return incoming.reset_index(drop=True)
    aligned = incoming.reindex(columns=current.columns)
    return pd.concat([current, aligned], ignore_index=True)


def unknown_columns(current: pd.DataFrame, incoming: pd.DataFrame) -> list[str]:
    if current is None or current.empty:
        return []
    return [c for c in incoming.columns if c not in current.columns]
