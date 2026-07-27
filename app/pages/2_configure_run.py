"""Configure & Run: engine settings and the batch launcher."""
import time

import streamlit as st

from app.components import db, run_state
from core.config import EngineConfig
from core.models.registry import ALL_MODEL_NAMES

st.set_page_config(page_title="Run · ForecastLens", page_icon="⚙️",
                   layout="wide")
st.title("⚙️ Configure & Run")

input_path = st.text_input(
    "Workbook path", value=st.session_state.get("input_path", ""),
    help="Set on the Data page, or type a path here.")

with st.form("config"):
    c1, c2, c3 = st.columns(3)
    with c1:
        horizon = st.select_slider("Forecast horizon (periods)",
                                   options=[3, 6, 12, 24], value=12)
        granularity = st.selectbox("Granularity", ["monthly", "weekly", "daily"])
        run_name = st.text_input("Run name", value="")
    with c2:
        min_hist = st.number_input("Competition threshold (min periods)",
                                   2, 24, 6)
        seasonal_min = st.number_input("Seasonal threshold (min periods)",
                                       8, 72, 24)
        windows = st.multiselect("Lookback windows (MA/WMA)",
                                 [2, 3, 4, 6, 9, 12], default=[3, 6, 12])
    with c3:
        enable_arima = st.checkbox(
            "Enable ARIMA (≥ 24 periods only)", value=False,
            help="Off by default: hard to explain and rarely better than "
                 "ETS/Theta on short series.")
        fast_mode = st.checkbox("Fast mode (skip window sweeps)", value=False)
        n_jobs = st.number_input("Parallel workers (-1 = auto)", -1, 32, -1)
        disabled = st.multiselect(
            "Disable models",
            [n for n in ALL_MODEL_NAMES if n not in
             ("Naive", "StandardRateAnchor", "CategoryPrior")])
    submitted = st.form_submit_button("🚀 Run forecast", type="primary")

if submitted:
    if not input_path:
        st.error("Set a workbook path first (Data page).")
    else:
        cfg = EngineConfig(
            granularity=granularity,
            forecast={"horizon": int(horizon)},
            gate={"min_history_competition": int(min_hist),
                  "seasonal_min_history": int(seasonal_min)},
            models={"enable_arima": enable_arima,
                    "lookback_windows": sorted(windows) or [3],
                    "disabled_models": disabled},
            fast_mode=fast_mode,
            n_jobs=int(n_jobs),
        )
        started = run_state.start_run(input_path, cfg, str(db.db_path()),
                                      run_name or None)
        if not started:
            st.warning("A run is already in progress.")

state = run_state.state()
if state["running"]:
    st.progress(state["fraction"], text=f"{state['stage']} "
                                        f"({state['fraction']:.0%})")
    time.sleep(1.5)
    st.rerun()
elif state["error"]:
    st.error(f"Run failed:\n\n```\n{state['error']}\n```")
elif state["run_id"]:
    st.success(f"Run **{state['run_id']}** complete. Open the Explorer or "
               "Portfolio page.")
    st.cache_data.clear()

st.subheader("Previous runs")
runs = db.load_runs(db.stamp())
if runs.empty:
    st.info("No runs yet.")
else:
    st.dataframe(runs, width="stretch", hide_index=True)
