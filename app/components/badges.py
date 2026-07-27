"""Portfolio triage: recommendation badges.

The Portfolio page's job is to shrink 820 series to the handful a planner
actually needs to look at.
"""
from __future__ import annotations

import pandas as pd

BADGES = {
    "ok": "✅ automatic forecast OK",
    "review": "👀 manual review",
    "structural": "📉 structural change",
    "quality": "⚠️ data quality issue",
    "declining": "🔻 confidence declining",
}


def recommend(series: pd.DataFrame, selections: pd.DataFrame,
              accuracy: pd.DataFrame | None = None) -> pd.Series:
    """One badge key per series, priority: quality > structural > declining >
    review > ok."""
    df = series.merge(
        selections[["series_id", "confidence_label", "is_override"]],
        on="series_id", how="left")
    df = df.set_index("series_id")

    badge = pd.Series("ok", index=df.index)

    low_conf = df["confidence_label"].fillna("low") == "low"
    badge[low_conf] = "review"

    if accuracy is not None and not accuracy.empty:
        acc = accuracy.dropna(subset=["actual_value"]).sort_values("period")
        for sid, g in acc.groupby("series_id"):
            if sid not in df.index or len(g) < 4:
                continue
            errs = g["abs_pct_error"].dropna()
            if len(errs) >= 4:
                half = len(errs) // 2
                if errs.iloc[half:].mean() > 1.5 * max(errs.iloc[:half].mean(), 1e-9):
                    badge[sid] = "declining"

    structural = df["structural_break_period"].notna()
    badge[structural] = "structural"

    quality = (df["data_quality"].fillna(0) < 0.6) | (df["is_orphan"] == 1)
    badge[quality] = "quality"

    return badge


def badge_label(key: str) -> str:
    return BADGES.get(key, key)
