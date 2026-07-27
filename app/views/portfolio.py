"""Portfolio & Export — the triage screen (which items need attention) plus
the download of everything this run produced."""
# --- path bootstrap ----------------------------------------------------------
# Make the repo root importable no matter how this script is launched:
# `streamlit run`, Streamlit Community Cloud, the frozen exe, or tests.
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# -----------------------------------------------------------------------------
import io

import pandas as pd
import streamlit as st

from app.components import badges, db, items as item_utils, ui

st.title("📋 Portfolio & Export")

run_id = db.pick_run(st)
if run_id is None:
    st.stop()

all_series = db.load_series(db.stamp())
selections = db.load_selections(db.stamp(), run_id)
accuracy = db.load_accuracy(db.stamp())
bom_items = db.load_items(db.stamp())
desc_lookup = item_utils.description_lookup(bom_items)

# A run may have been scoped to some items only — show what it produced.
series = all_series[all_series["series_id"].isin(selections["series_id"])]
if len(series) < len(all_series):
    st.info(f"This run covered {len(series)} of {len(all_series)} series. "
            "Other items keep the results from the run that last included "
            "them — switch runs above to see those.")

badge = badges.recommend(series, selections, accuracy)
table = series.merge(
    selections[["series_id", "model_name", "window", "mase", "confidence",
                "confidence_label", "is_override", "route"]],
    on="series_id", how="left")
table["recommendation"] = table["series_id"].map(badge).map(badges.badge_label)
table["description"] = table["item_code"].map(
    lambda c: desc_lookup.get(str(c), ""))

BADGE_HELP = {
    "ok": "Nothing to do — the forecast validated well and the data is sound.",
    "review": "Low confidence: thin, noisy or brand-new history. Sanity-check "
              "the forecast before relying on it.",
    "structural": "The item's behaviour shifted at some point — the history "
                  "before the shift may no longer represent it.",
    "quality": "Data problems: poor quality score, or no driver record at "
               "all (orphan). Fix the data first; these come first.",
    "declining": "Forecast accuracy has been getting worse over recent "
                 "actuals imports — the item may be changing.",
}

counts = badge.value_counts()
cols = st.columns(len(badges.BADGES))
for col, (key, label) in zip(cols, badges.BADGES.items()):
    col.metric(label, int(counts.get(key, 0)), help=BADGE_HELP[key])

st.caption("Priority runs left to right: fix data-quality issues first, then "
           "structural changes, declining accuracy, and manual reviews. "
           "Everything else is running fine on its own.")

ui.section("Filter and sort",
           "Narrow the list to the items you want to work on. Every item is "
           "shown by code and description with its line and output type.")
c1, c2, c3, c4 = st.columns(4)
with c1:
    f_badge = st.multiselect(
        "Recommendation", list(badges.BADGES.values()),
        help="Show only items carrying the selected badges.")
with c2:
    f_mode = st.multiselect(
        "Mode", ["relative", "absolute"],
        help="Relative items are driver-dependent; Absolute items are not.")
with c3:
    f_class = st.multiselect(
        "Demand pattern", sorted(series["pattern_class"].dropna().unique()),
        help="Smooth, erratic, intermittent, lumpy, or too short to classify.")
with c4:
    f_conf = st.multiselect(
        "Confidence", ["low", "medium", "high"],
        help="How much the engine trusts each forecast.")

view = table
if f_badge:
    view = view[view["recommendation"].isin(f_badge)]
if f_mode:
    view = view[view["mode"].isin(f_mode)]
if f_class:
    view = view[view["pattern_class"].isin(f_class)]
if f_conf:
    view = view[view["confidence_label"].isin(f_conf)]

sort_by = st.selectbox(
    "Sort by", ["confidence", "mase", "data_quality", "n_reliable",
                "description", "item_code"],
    help="confidence lowest-first surfaces the shakiest forecasts; mase "
         "highest-first surfaces the worst back-tested fits.")
view = view.sort_values(sort_by, na_position="last")

show = view[["item_code", "description", "line", "output_type",
             "recommendation", "mode", "pattern_class", "model_name",
             "confidence_label", "confidence", "mase", "data_quality",
             "n_observed", "n_reliable", "is_orphan",
             "structural_break_period", "is_override"]]
ui.table(show,
         "One row per forecast series. model_name is the model the engine "
         "chose; mase is its back-tested error (lower is better); "
         "n_reliable is how many periods were usable for fitting; "
         "is_orphan flags a missing driver denominator.",
         hide_index=True, height=520)
st.caption(f"{len(view)} of {len(table)} series shown. Open any item in the "
           "Explorer for its full story.")

st.download_button(
    "⬇️ Download this view (CSV)",
    show.to_csv(index=False).encode(),
    file_name="portfolio.csv", mime="text/csv",
    help="Exports exactly the rows and columns shown above.")

# --- full export --------------------------------------------------------------
st.divider()
ui.section("Export the full results",
           "Download everything this run produced, not just the table above. "
           "Every exported row carries item code, description, line and "
           "output type as separate columns.")

forecasts = db.load_forecasts(db.stamp(), run_id)
warnings = db.load_warnings(db.stamp(), run_id)

e1, e2 = st.columns(2)
with e1:
    export_scope = st.radio(
        "Which items to export", ["Everything in this run",
                                  "Only the filtered rows above"],
        help="The filtered option exports exactly the items left after the "
             "recommendation, mode, pattern and confidence filters.")
with e2:
    what = st.multiselect(
        "Sheets to include",
        ["forecasts", "selections", "series", "warnings"],
        default=["forecasts", "selections", "series", "warnings"],
        help="forecasts = the numbers per future period. selections = which "
             "model won each item and why. series = each item's behaviour "
             "profile. warnings = the validation report.")

scoped_ids = set(view["series_id"]) if export_scope.startswith("Only") \
    else set(table["series_id"])
scoped_series = series[series["series_id"].isin(scoped_ids)]

frames: dict[str, pd.DataFrame] = {}
if "forecasts" in what:
    frames["forecasts"] = item_utils.add_identity(
        forecasts[forecasts["series_id"].isin(scoped_ids)], series, bom_items)
if "selections" in what:
    frames["selections"] = item_utils.add_identity(
        selections[selections["series_id"].isin(scoped_ids)]
        .drop(columns=["rejected_json"], errors="ignore"), series, bom_items)
if "series" in what:
    out = scoped_series.copy()
    out.insert(1, "description",
               out["item_code"].map(lambda c: desc_lookup.get(str(c), "")))
    frames["series"] = out.drop(columns=["series_id"])
if "warnings" in what:
    w = warnings.copy()
    if "series_id" in w.columns:
        parts = w["series_id"].fillna("").str.split("|", expand=True)
        w["item_code"] = parts[0].replace("", pd.NA)
        w["description"] = w["item_code"].map(
            lambda c: desc_lookup.get(str(c), "") if pd.notna(c) else "")
        w["line"] = parts[1] if parts.shape[1] > 1 else pd.NA
        w["output_type"] = parts[2] if parts.shape[1] > 2 else pd.NA
        w = w.drop(columns=["series_id"])
    frames["warnings"] = w

st.caption(f"{len(scoped_series)} series in the export scope.")

buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
    for name, df in frames.items():
        df.to_excel(writer, sheet_name=name[:31], index=False)

d1, d2 = st.columns(2)
with d1:
    st.download_button(
        "⬇️ Download Excel workbook", buffer.getvalue(),
        file_name="forecastlens_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        help="One sheet per selection above, covering the items in scope.")
with d2:
    if frames:
        pick = st.selectbox("Single table as CSV", list(frames),
                            help="Which table to download on its own.")
        st.download_button(
            "⬇️ Download CSV", frames[pick].to_csv(index=False).encode(),
            file_name=f"forecastlens_{pick}.csv", mime="text/csv",
            help="Comma-separated values, openable in Excel or any tool.")
