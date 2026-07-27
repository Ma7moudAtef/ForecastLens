"""Accuracy — forecast-vs-actual tracking over time."""
# --- path bootstrap ----------------------------------------------------------
# Make the repo root importable no matter how this script is launched:
# `streamlit run`, Streamlit Community Cloud, the frozen exe, or tests.
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# -----------------------------------------------------------------------------
import tempfile

import streamlit as st

from app.components import db, filebrowser, items as item_utils, ui
from core.learn.accuracy import import_actuals

st.title("🎯 Accuracy")

ui.section("Import actuals",
           "Once the forecast periods have passed, bring in a workbook "
           "containing what actually happened. The engine compares it with "
           "what it predicted, records the error, and flags items whose "
           "accuracy is drifting.")
col_up, col_browse = st.columns([4, 1])
with col_up:
    uploaded = st.file_uploader(
        "Workbook with newer consumption history", type=["xlsx"],
        help="Same format as your input workbook, containing the periods "
             "that have since been recorded.")
with col_browse:
    st.write("")
    picked = filebrowser.path_picker("acc_browse")

run_for_compare = db.pick_run(st)

source_path = None
if uploaded is not None:
    tmp = Path(tempfile.gettempdir()) / "forecastlens_actuals.xlsx"
    tmp.write_bytes(uploaded.getvalue())
    source_path = tmp
elif picked:
    source_path = Path(picked)

if source_path and run_for_compare and st.button(
        "Import & compare", type="primary",
        help="Match stored forecasts to the actuals in this file and update "
             "the accuracy history."):
    with st.spinner("Comparing stored forecasts to actuals…"):
        result = import_actuals(source_path, db.db_path(), run_for_compare)
    st.success(f"Matched {result.n_matched} forecast period(s) across "
               f"{result.n_series} series; {result.n_drift} series flagged "
               "for drift.")
    st.cache_data.clear()

accuracy = db.load_accuracy(db.stamp())
if accuracy.empty:
    st.info("No accuracy history yet — import actuals once a run's forecast "
            "periods have elapsed.")
    st.stop()

acc = accuracy.dropna(subset=["actual_value"])
series = db.load_series(db.stamp())
bom_items = db.load_items(db.stamp())
desc_lookup = item_utils.description_lookup(bom_items)

ui.section("Error over time",
           "How far the forecasts have been from reality, tracked as new "
           "actuals arrive. Lower is better.")
c1, c2 = st.columns(2)
with c1:
    st.line_chart(acc.groupby("period")["abs_pct_error"].mean())
    ui.help_icon("Average absolute percentage error per period, across every "
                 "series that had a forecast for it.")
with c2:
    st.bar_chart(acc.groupby("model_name")["abs_pct_error"].mean()
                 .sort_values())
    ui.help_icon("Average error by the model that produced the forecast — "
                 "which methods are earning their place on your data.")

ui.section("Per-item accuracy",
           "Forecast versus actual, period by period, for one item.")
detailed = item_utils.add_identity(acc, series, bom_items)
labels = item_utils.build_labels(detailed["item_code"].dropna().unique(),
                                 desc_lookup)
pick_label = st.selectbox(
    "Item (by description)", list(labels),
    help="Items are listed by description with the code after the dash.")
code = labels[pick_label]
g = detailed[detailed["item_code"] == code].sort_values("period")

ui.table(g[["item_code", "description", "line", "output_type", "period",
            "forecast_value", "actual_value", "error", "abs_pct_error",
            "model_name"]],
         "error = forecast minus actual (positive means the forecast was too "
         "high). abs_pct_error = the size of that miss as a percentage of "
         "the actual.", hide_index=True)

errs = g["abs_pct_error"].dropna()
if len(errs) >= 4:
    half = len(errs) // 2
    early, late = errs.iloc[:half].mean(), errs.iloc[half:].mean()
    if late > 1.5 * max(early, 1e-9):
        st.warning(f"Drift alert: recent error ({late:.0f}%) is well above "
                   f"the earlier level ({early:.0f}%). This item is flagged "
                   "for re-evaluation on the Portfolio page.")
