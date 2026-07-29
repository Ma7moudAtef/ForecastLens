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
import pandas as pd
import streamlit as st

from app.components import badges, db, items as item_utils, ui
from core.export import (
    SHEETS as EXPORT_SHEETS,
    build_frames,
    with_dictionary,
    workbook_bytes,
)
from core.export_guide import SHEET_PURPOSE, tooltip

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
    lambda c: item_utils.describe(c, desc_lookup))

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
        list(EXPORT_SHEETS), default=list(EXPORT_SHEETS),
        help="forecasts = the numbers per future period. selections = which "
             "model won each item and why. series = each item's behaviour "
             "profile. context = whether operating conditions change each "
             "item's consumption. warnings = the validation report.")

scoped_ids = set(view["series_id"]) if export_scope.startswith("Only") \
    else set(table["series_id"])

# Built by core.export — the identical code the CLI and the frozen exe use,
# so a download from the web app and one from the exe are the same file.
frames = build_frames(db.db_path(), run_id, series_ids=scoped_ids,
                      sheets=tuple(what))
st.caption(f"{len(scoped_ids)} series in the export scope.")


@st.cache_data(show_spinner="Preparing the workbook…")
def _workbook(stamp: float, run: str, sheets: tuple[str, ...],
              series_ids: tuple[str, ...]) -> bytes:
    """Byte-for-byte the workbook core.export writes, data dictionary
    included — the browser download and `ForecastLens --export` must not
    drift apart.

    Cached because a download button needs its bytes up front, so without
    this the whole workbook is rebuilt on every checkbox and every sort — a
    few seconds each time on a full catalogue.
    """
    return workbook_bytes(build_frames(db.db_path(), run,
                                       series_ids=set(series_ids),
                                       sheets=sheets))


workbook = _workbook(db.stamp(), run_id, tuple(what),
                     tuple(sorted(scoped_ids)))

d1, d2 = st.columns(2)
with d1:
    st.download_button(
        "⬇️ Download Excel workbook", workbook,
        file_name="forecastlens_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        help="One sheet per selection above, covering the items in scope, "
             "plus a data_dictionary sheet explaining every column and why "
             "it is there.")
with d2:
    if frames:
        pick = st.selectbox("Single table as CSV", list(frames),
                            help="Which table to download on its own.")
        st.download_button(
            "⬇️ Download CSV", frames[pick].to_csv(index=False).encode(),
            file_name=f"forecastlens_{pick}.csv", mime="text/csv",
            help="Comma-separated values, openable in Excel or any tool.")

# --- preview before downloading -----------------------------------------------
st.divider()
ui.section("Look inside the workbook first",
           "Exactly the sheets the download contains, in the same order. "
           "Hover the ❓ on any column heading to see what it holds and why "
           "you would use it — the same text the workbook's own "
           "data_dictionary sheet carries.")

PREVIEW_ROWS = 200
previewed = with_dictionary(frames)
if not previewed:
    st.info("Choose at least one sheet above to preview it.")
else:
    for tab, name in zip(st.tabs([f"📄 {n}" for n in previewed]), previewed):
        with tab:
            frame = previewed[name]
            purpose = SHEET_PURPOSE.get(name, "")
            if purpose:
                st.caption(purpose)
            if frame.empty:
                st.info("This sheet has no rows for the current scope.")
                continue
            shown = frame.head(PREVIEW_ROWS)
            ui.table(
                shown,
                f"The '{name}' sheet of the download. Every column carries "
                "its own ❓ explaining what it is and why you need it.",
                column_help={c: tooltip(name, c) for c in frame.columns},
                hide_index=True)
            st.caption(
                f"{len(frame):,} row(s) in the download"
                + (f" — showing the first {PREVIEW_ROWS:,}."
                   if len(frame) > PREVIEW_ROWS else "."))
