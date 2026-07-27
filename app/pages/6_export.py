"""Export — Excel/CSV downloads of forecasts, selections and warnings."""
# --- path bootstrap ----------------------------------------------------------
# Make the repo root importable no matter how this script is launched:
# `streamlit run`, Streamlit Community Cloud, the frozen exe, or tests.
# `streamlit run app/main.py` puts app/ on sys.path, NOT the project root, so
# `from app...` / `from core...` fail without this (ModuleNotFoundError).
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# -----------------------------------------------------------------------------
import io

import pandas as pd
import streamlit as st

from app.components import auth, db

st.set_page_config(page_title="Export · ForecastLens", page_icon="📤",
                   layout="wide")
auth.require_secret()
st.title("📤 Export")

run_id = db.pick_run(st)
if run_id is None:
    st.stop()

series = db.load_series(db.stamp())
selections = db.load_selections(db.stamp(), run_id)
forecasts = db.load_forecasts(db.stamp(), run_id)
warnings = db.load_warnings(db.stamp(), run_id)

# --- scope --------------------------------------------------------------------
st.subheader("Scope")
c1, c2 = st.columns(2)
with c1:
    modes = st.multiselect("Modes", ["relative", "absolute"])
with c2:
    items = st.multiselect("Items", sorted(series["item_code"].dropna().unique()))

scoped = series
if modes:
    scoped = scoped[scoped["mode"].isin(modes)]
if items:
    scoped = scoped[scoped["item_code"].isin(items)]
sids = set(scoped["series_id"])

fc = forecasts[forecasts["series_id"].isin(sids)]
sel = selections[selections["series_id"].isin(sids)]
st.caption(f"{len(scoped)} series · {len(fc)} forecast rows in scope.")

what = st.multiselect(
    "Sheets to include",
    ["forecasts", "selections", "series", "warnings"],
    default=["forecasts", "selections", "series", "warnings"])

# --- excel --------------------------------------------------------------------
frames: dict[str, pd.DataFrame] = {}
if "forecasts" in what:
    frames["forecasts"] = fc.merge(
        series[["series_id", "item_code", "line", "output_type", "mode",
                "target_uom"]], on="series_id")
if "selections" in what:
    frames["selections"] = sel.drop(columns=["rejected_json"], errors="ignore")
if "series" in what:
    frames["series"] = scoped
if "warnings" in what:
    frames["warnings"] = warnings

buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
    for name, df in frames.items():
        df.to_excel(writer, sheet_name=name[:31], index=False)

st.download_button(
    "⬇️ Download Excel workbook",
    buffer.getvalue(),
    file_name=f"forecastlens_{run_id}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary")

st.subheader("Single-table CSV")
pick = st.selectbox("Table", list(frames) or ["forecasts"])
if frames:
    st.download_button(
        "⬇️ Download CSV",
        frames[pick].to_csv(index=False).encode(),
        file_name=f"forecastlens_{run_id}_{pick}.csv",
        mime="text/csv")
