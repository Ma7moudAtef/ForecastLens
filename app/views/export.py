"""Export — Excel/CSV downloads of forecasts, selections and warnings."""
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

from app.components import db, items as item_utils, ui

st.title("📤 Export")

run_id = db.pick_run(st)
if run_id is None:
    st.stop()

series = db.load_series(db.stamp())
selections = db.load_selections(db.stamp(), run_id)
forecasts = db.load_forecasts(db.stamp(), run_id)
warnings = db.load_warnings(db.stamp(), run_id)
bom_items = db.load_items(db.stamp())
desc_lookup = item_utils.description_lookup(bom_items)

ui.section("What to export",
           "Choose which items and sheets to include. Every exported row "
           "carries item code, description, line and output type as separate "
           "columns.")
c1, c2 = st.columns(2)
with c1:
    modes = st.multiselect(
        "Modes", ["relative", "absolute"],
        help="Empty = both. Relative items are driver-dependent; Absolute "
             "items are independent.")
with c2:
    labels = item_utils.build_labels(
        series["item_code"].dropna().unique(), desc_lookup)
    picked_labels = st.multiselect(
        "Items (by description)", list(labels),
        help="Empty = every item. Type to search by description or code.")
    picked_items = [labels[l] for l in picked_labels]

scoped = series
if modes:
    scoped = scoped[scoped["mode"].isin(modes)]
if picked_items:
    scoped = scoped[scoped["item_code"].isin(picked_items)]
sids = set(scoped["series_id"])

fc = forecasts[forecasts["series_id"].isin(sids)]
sel = selections[selections["series_id"].isin(sids)]
st.caption(f"{len(scoped)} series · {len(fc)} forecast rows in scope.")

what = st.multiselect(
    "Sheets to include", ["forecasts", "selections", "series", "warnings"],
    default=["forecasts", "selections", "series", "warnings"],
    help="forecasts = the numbers per future period. selections = which "
         "model won each item and why. series = each item's behaviour "
         "profile. warnings = the validation report.")

frames: dict[str, pd.DataFrame] = {}
if "forecasts" in what:
    frames["forecasts"] = item_utils.add_identity(fc, series, bom_items)
if "selections" in what:
    frames["selections"] = item_utils.add_identity(
        sel.drop(columns=["rejected_json"], errors="ignore"), series, bom_items)
if "series" in what:
    out = scoped.copy()
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

buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
    for name, df in frames.items():
        df.to_excel(writer, sheet_name=name[:31], index=False)

st.download_button(
    "⬇️ Download Excel workbook", buffer.getvalue(),
    file_name=f"forecastlens_{run_id}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    help="One sheet per selection above, covering the items in scope.")

ui.section("Single table as CSV",
           "If you only need one of the tables, download it on its own.")
if frames:
    pick = st.selectbox("Table", list(frames),
                        help="Which table to download as CSV.")
    st.download_button(
        "⬇️ Download CSV", frames[pick].to_csv(index=False).encode(),
        file_name=f"forecastlens_{run_id}_{pick}.csv", mime="text/csv",
        help="Comma-separated values, openable in Excel or any tool.")
