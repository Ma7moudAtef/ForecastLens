"""Configure & Run — engine settings and the batch launcher."""
# --- path bootstrap ----------------------------------------------------------
# Make the repo root importable no matter how this script is launched:
# `streamlit run`, Streamlit Community Cloud, the frozen exe, or tests.
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# -----------------------------------------------------------------------------
import time

import streamlit as st

from app.components import db, filebrowser, paths, run_state, ui
from core.config import EngineConfig
from core.models.registry import ALL_MODEL_NAMES

st.title("⚙️ Configure & Run")

default_path = st.session_state.get("input_path") or (
    str(paths.default_input_path()) if paths.default_input_path() else "")

ui.section("Input workbook",
           "The data this run will read. The bundled default workbook is "
           "preloaded, so you can run immediately without choosing anything.")
col_path, col_browse = st.columns([4, 1])
with col_path:
    typed_path = st.text_input(
        "Workbook path", value=default_path,
        help="Set on the Data page, typed here, or picked with the Browse "
             "button beside this box.")
with col_browse:
    st.write("")
    picked = filebrowser.path_picker("run_browse")
input_path = picked or typed_path
if picked:
    st.session_state["input_path"] = picked
    st.rerun()

with st.form("config"):
    c1, c2, c3 = st.columns(3)
    with c1:
        horizon = st.select_slider(
            "Forecast horizon (periods)", options=[3, 6, 12, 24], value=12,
            help="How many periods into the future to forecast. Longer "
                 "horizons always carry wider uncertainty bands.")
        granularity = st.selectbox(
            "Granularity", ["monthly", "weekly", "daily"],
            help="The period size of your data. The seasonal cycle length "
                 "follows from this — 12 for monthly, 52 for weekly, 7 for "
                 "daily — nothing is hardcoded.")
        run_name = st.text_input(
            "Run name", value="",
            help="A label to recognise this run later. Optional.")
    with c2:
        min_hist = st.number_input(
            "Competition threshold (min periods)", 2, 24, 6,
            help="Below this many usable periods an item skips the model "
                 "competition and uses the cold-start ladder (standard rate, "
                 "then category prior, then last actual). Its confidence is "
                 "capped at low.")
        seasonal_min = st.number_input(
            "Seasonal threshold (min periods)", 8, 72, 24,
            help="Seasonal models need two full cycles to estimate a pattern "
                 "honestly. Below this, they are kept out of the "
                 "competition.")
        windows = st.multiselect(
            "Lookback windows", [2, 3, 4, 6, 9, 12], default=[3, 6, 12],
            help="Window lengths tried by the moving-average models — how "
                 "many recent periods count as 'still representative'.")
    with c3:
        enable_arima = st.checkbox(
            "Enable ARIMA (24+ periods only)", value=False,
            help="Off by default: on short histories ARIMA is unstable, hard "
                 "to explain, and rarely beats the smoothing models.")
        fast_mode = st.checkbox(
            "Fast mode", value=False,
            help="Skip the lookback-window sweep — fewer candidates, quicker "
                 "run, slightly less tuning.")
        n_jobs = st.number_input(
            "Parallel workers (-1 = auto)", -1, 32, -1,
            help="How many CPU workers fit models at once. -1 uses all "
                 "cores but one.")
        disabled = st.multiselect(
            "Disable models",
            [n for n in ALL_MODEL_NAMES if n not in
             ("Naive", "StandardRateAnchor", "CategoryPrior")],
            help="Remove specific models from every competition. The "
                 "fallback models cannot be disabled — something must always "
                 "be able to produce a forecast.")
    submitted = st.form_submit_button(
        "🚀 Run forecast", type="primary",
        help="Start the batch. It runs in the background and writes results "
             "to the local database; you can watch progress here and then "
             "open the Explorer.")

if submitted:
    if not input_path or not Path(input_path).exists():
        st.error("No readable workbook at that path — pick one on the Data "
                 "page or with Browse above.")
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
        st.session_state["input_path"] = input_path
        if not run_state.start_run(input_path, cfg, str(db.db_path()),
                                   run_name or None):
            st.warning("A run is already in progress.")

state = run_state.state()
if state["running"]:
    st.progress(state["fraction"],
                text=f"{state['stage']} ({state['fraction']:.0%})")
    time.sleep(1.5)
    st.rerun()
elif state["error"]:
    st.error(f"Run failed:\n\n```\n{state['error']}\n```")
elif state["run_id"]:
    st.success(f"Run **{state['run_id']}** complete — open the Explorer or "
               "Portfolio page.")
    st.cache_data.clear()

ui.section("Previous runs",
           "Every completed run is kept. You can reopen any of them from the "
           "run picker at the top of the result pages.")
runs = db.load_runs(db.stamp())
if runs.empty:
    st.info("No runs yet.")
else:
    ui.table(runs, "run_id identifies the run; duration_s is how long it "
                   "took; n_series is how many forecast series it produced.",
             hide_index=True)
