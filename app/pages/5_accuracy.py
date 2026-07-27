"""Accuracy — forecast-vs-actual tracking over time.

Importing a newer workbook compares stored forecasts against the actuals
that have since materialized, records the error, and flags drift.
"""
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from app.components import auth, db
from core.learn.accuracy import import_actuals

st.set_page_config(page_title="Accuracy · ForecastLens", page_icon="🎯",
                   layout="wide")
auth.require_secret()
st.title("🎯 Accuracy")

# --- import actuals -----------------------------------------------------------
st.subheader("Import actuals")
st.caption("Upload a workbook containing newer consumption history. Stored "
           "forecasts are compared with what actually happened; accuracy "
           "history accumulates run over run.")
uploaded = st.file_uploader("Workbook with actuals", type=["xlsx"])
run_for_compare = db.pick_run(st)

if uploaded is not None and run_for_compare and st.button("Import & compare"):
    tmp = Path(tempfile.gettempdir()) / "forecastlens_actuals.xlsx"
    tmp.write_bytes(uploaded.getvalue())
    with st.spinner("Comparing stored forecasts to actuals…"):
        result = import_actuals(tmp, db.db_path(), run_for_compare)
    st.success(f"Matched {result.n_matched} forecast period(s) across "
               f"{result.n_series} series; {result.n_drift} series flagged "
               "for drift.")
    st.cache_data.clear()

# --- accuracy history ---------------------------------------------------------
accuracy = db.load_accuracy(db.stamp())
if accuracy.empty:
    st.info("No accuracy history yet — import actuals after a run's "
            "forecast periods have elapsed.")
    st.stop()

acc = accuracy.dropna(subset=["actual_value"])
st.subheader("Error over time")
c1, c2 = st.columns(2)
with c1:
    by_period = (acc.groupby("period")["abs_pct_error"].mean() * 1.0)
    st.line_chart(by_period)
    st.caption("Mean absolute % error per period (lower is better).")
with c2:
    by_model = acc.groupby("model_name")["abs_pct_error"].mean().sort_values()
    st.bar_chart(by_model)
    st.caption("Mean absolute % error per model.")

st.subheader("Per-series accuracy")
sid = st.selectbox("Series", sorted(acc["series_id"].unique()))
g = acc[acc["series_id"] == sid].sort_values("period")
show = g[["period", "forecast_value", "actual_value", "error",
          "abs_pct_error", "model_name", "run_id"]]
st.dataframe(show, width="stretch", hide_index=True)

# drift check: recent error vs early error
errs = g["abs_pct_error"].dropna()
if len(errs) >= 4:
    half = len(errs) // 2
    early, late = errs.iloc[:half].mean(), errs.iloc[half:].mean()
    if late > 1.5 * max(early, 1e-9):
        st.warning(f"Drift alert: recent error ({late:.0f}%) is well above "
                   f"the earlier level ({early:.0f}%). The series is flagged "
                   "for re-evaluation on the Portfolio page.")
