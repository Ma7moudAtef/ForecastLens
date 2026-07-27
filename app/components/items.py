"""Item identity helpers.

Users pick items by DESCRIPTION first; the code is always visible but
secondary. Internally everything still runs on item_code — and the internal
series_id never reaches the user: every user-facing table shows code,
description, line and output type as separate columns.
"""
from __future__ import annotations

import pandas as pd

ID_COLS = ["item_code", "description", "line", "output_type"]


def label_of(code: str, description: str | None) -> str:
    if description and str(description).strip() and str(description) != "nan":
        return f"{description} — {code}"
    return f"{code} (no description)"


def description_lookup(items: pd.DataFrame) -> dict[str, str]:
    """item_code -> description from an items/bom table (either internal
    'description' or external 'item_description' column name)."""
    if items is None or items.empty:
        return {}
    col = "description" if "description" in items.columns else "item_description"
    if col not in items.columns:
        return {}
    sub = items.dropna(subset=["item_code"]).drop_duplicates("item_code")
    return {str(k): (None if pd.isna(v) else str(v))
            for k, v in zip(sub["item_code"], sub[col])}


def build_labels(codes, lookup: dict[str, str]) -> dict[str, str]:
    """Ordered {label: code}; described items first, sorted by description,
    then bare codes."""
    described, bare = [], []
    for code in sorted(set(str(c) for c in codes)):
        desc = lookup.get(code)
        (described if desc else bare).append((label_of(code, desc), code))
    described.sort(key=lambda t: t[0].lower())
    return dict(described + bare)


def expand_series_id(df: pd.DataFrame, lookup: dict[str, str],
                     column: str = "series_id") -> pd.DataFrame:
    """Replace a 'item|line|output' identifier column with the four identity
    columns. Safe on an empty frame — splitting an empty column yields a
    frame with no columns at all, which naive indexing turns into a
    KeyError."""
    out = df.copy()
    if column not in out.columns:
        return out
    if out.empty:
        out = out.drop(columns=[column])
        for name in ID_COLS:
            out[name] = pd.Series(dtype="object")
        return out
    parts = out[column].fillna("").astype(str).str.split("|", expand=True)
    for idx, name in enumerate(["item_code", "line", "output_type"]):
        out[name] = parts[idx].replace("", pd.NA) if idx in parts.columns \
            else pd.NA
    out["description"] = out["item_code"].map(
        lambda c: lookup.get(str(c), "") if pd.notna(c) else "")
    return out.drop(columns=[column])


def add_identity(df: pd.DataFrame, series: pd.DataFrame,
                 items: pd.DataFrame) -> pd.DataFrame:
    """Replace series_id with code / description / line / output columns.
    The identity columns come first; series_id is dropped from the result."""
    lookup = description_lookup(items)
    out = df.merge(series[["series_id", "item_code", "line", "output_type"]],
                   on="series_id", how="left")
    out["description"] = out["item_code"].map(
        lambda c: lookup.get(str(c)) or "")
    rest = [c for c in out.columns if c not in ID_COLS + ["series_id"]]
    return out[ID_COLS + rest]
