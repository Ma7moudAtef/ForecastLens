"""Data page: load a workbook, validate, review issues, declare modes."""
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
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from app.components import auth, db
from core.analyze.statistics import analyze_all
from core.config import AppConfig, EngineConfig
from core.io.excel_source import ExcelSource
from core.prep.series_builder import build_series
from core.validate import rules

st.set_page_config(page_title="Data · ForecastLens", page_icon="🗂️",
                   layout="wide")
auth.require_secret()
st.title("🗂️ Data")

app_cfg = AppConfig()
cfg = EngineConfig()

# --- source selection ---------------------------------------------------------
st.subheader("Workbook")
uploaded = st.file_uploader(
    "Upload an Excel workbook (bom, consumption, prod, consumption_figs)",
    type=[e.lstrip(".") for e in app_cfg.allowed_upload_extensions])
default_path = st.text_input(
    "…or a file path", value=st.session_state.get("input_path", ""))

path: Path | None = None
if uploaded is not None:
    if uploaded.size > app_cfg.max_upload_mb * 1024 * 1024:
        st.error(f"File exceeds the {app_cfg.max_upload_mb} MB cap.")
    else:
        tmp = Path(tempfile.gettempdir()) / "forecastlens_upload.xlsx"
        tmp.write_bytes(uploaded.getvalue())
        path = tmp
elif default_path:
    path = Path(default_path)

if path is None:
    st.info("Choose a workbook to validate. Nothing is computed until you "
            "launch a run.")
    st.stop()

if not path.exists():
    st.error(f"File not found: {path}")
    st.stop()

st.session_state["input_path"] = str(path)


@st.cache_data(show_spinner="Validating workbook…")
def _load_and_validate(p: str, mtime: float):
    raw = ExcelSource(p).load()
    warnings = rules.run_all(raw, cfg)
    overrides = {r.item_code: r.mode
                 for r in db.repo().get_mode_overrides().itertuples()}
    prep = build_series(raw, cfg, mode_overrides=overrides)
    analyzed = analyze_all(prep, cfg)
    wdf = pd.DataFrame([{
        "severity": w.severity.value, "code": w.code, "scope": w.scope(),
        "count": w.count, "message": w.message}
        for w in warnings + prep.warnings])
    summary = {
        "consumption_rows": len(raw.consumption),
        "items": raw.consumption["item_code"].nunique(),
        "bom_items": len(raw.items),
        "driver_rows": len(raw.driver),
        "date_min": str(raw.consumption["date"].min().date()),
        "date_max": str(raw.consumption["date"].max().date()),
    }
    return summary, wdf, analyzed


summary, warnings_df, analyzed = _load_and_validate(
    str(path), path.stat().st_mtime)

# --- summary ------------------------------------------------------------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Consumption rows", f"{summary['consumption_rows']:,}")
c2.metric("Items", summary["items"])
c3.metric("Atomic series", len(analyzed))
c4.metric("Driver rows", f"{summary['driver_rows']:,}")
c5.metric("Coverage", f"{summary['date_min']} → {summary['date_max']}")

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Mode split")
    mode_counts = analyzed.groupby("mode")["item_code"].nunique()
    st.bar_chart(mode_counts)
    st.caption("Mode is a property of the material's nature — a Relative "
               "series never flips to Absolute because of missing data.")
with col_b:
    st.subheader("Demand pattern classes")
    st.bar_chart(analyzed["pattern_class"].value_counts())

# --- orphans, prominently -----------------------------------------------------
orphans = analyzed[analyzed["is_orphan"] == 1]
if not orphans.empty:
    st.error(
        f"**{len(orphans)} orphan series need planner resolution.** "
        "These have a consumption rate but no driver record exists for their "
        "(line, output) in any period — the denominator does not exist. They "
        "stay Relative and are excluded from demand reconstruction; no "
        "denominator is guessed and nothing is deleted. Provide driver data "
        "for the combination, or declare the item Absolute below.")
    st.dataframe(orphans[["series_id", "item_code", "line", "output_type",
                          "mode", "n_observed"]], width="stretch")

# --- validation report --------------------------------------------------------
st.subheader("Validation report")
if warnings_df.empty:
    st.success("No issues found.")
else:
    sev_order = ["fatal", "warning", "info"]
    tabs = st.tabs([f"{s} ({(warnings_df['severity'] == s).sum()})"
                    for s in sev_order])
    for tab, sev in zip(tabs, sev_order):
        with tab:
            sub = warnings_df[warnings_df["severity"] == sev]
            if sub.empty:
                st.write("None.")
            else:
                st.dataframe(sub[["code", "scope", "count", "message"]],
                             width="stretch", hide_index=True)
    if (warnings_df["severity"] == "fatal").any():
        st.error("Fatal issues block the run. Fix the workbook first.")
    else:
        st.success("No fatal issues — a run may proceed. Warnings never "
                   "delete data; the engine flags and continues.")

# --- declared mode control ----------------------------------------------------
st.subheader("Declare an item's mode")
st.caption("A declaration wins over what the data suggests, permanently, "
           "until cleared. Use it when you know a material is driver-"
           "dependent (Relative) or independent (Absolute) regardless of "
           "recorded history.")
items = sorted(analyzed["item_code"].unique())
col1, col2, col3 = st.columns([2, 1, 2])
with col1:
    pick = st.selectbox("Item", items)
with col2:
    mode_choice = st.selectbox("Mode", ["relative", "absolute"])
with col3:
    reason = st.text_input("Reason (recorded)")
if st.button("Declare mode"):
    db.repo().set_mode_override(pick, mode_choice, reason)
    st.success(f"{pick} declared {mode_choice}. Takes effect on the next run.")
    st.cache_data.clear()

existing = db.repo().get_mode_overrides()
if not existing.empty:
    st.dataframe(existing, width="stretch", hide_index=True)
    clear = st.selectbox("Clear a declaration", existing["item_code"])
    if st.button("Clear"):
        db.repo().clear_mode_override(clear)
        st.cache_data.clear()
        st.rerun()
