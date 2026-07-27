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

import pandas as pd

from app.components import db, filebrowser, items as item_utils, paths, run_state, ui
from core.config import EngineConfig
from core.models.registry import ALL_MODEL_NAMES

st.title("⚙️ Configure & Run")


@st.cache_data(show_spinner="Reading the item list…")
def read_catalogue(path: str) -> dict[str, str]:
    """{label: item_code} for every item in the workbook, description first."""
    try:
        bom = pd.read_excel(path, sheet_name="bom", engine="openpyxl")
    except Exception:
        return {}
    lookup = item_utils.description_lookup(bom)
    return item_utils.build_labels(bom["item_code"].dropna().unique(), lookup)

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

ui.section("Which materials to forecast",
           "Run the whole catalogue, or just the items you care about right "
           "now. A scoped run is much faster and is scored exactly the same "
           "way — the engine still studies the full dataset, so cold-start "
           "items keep borrowing behaviour from all their category siblings.")

scope_items: list[str] = []
scope_choice = st.radio(
    "Run scope", ["All materials", "A single item", "A list of items"],
    horizontal=True,
    help="All materials = every item in the workbook. Single/list = forecast "
         "only what you select; everything else keeps the results from its "
         "last run.")

if scope_choice != "All materials":
    catalogue = read_catalogue(input_path) if input_path else {}
    if not catalogue:
        st.warning("Load a readable workbook above to choose items.")
    elif scope_choice == "A single item":
        pick = st.selectbox(
            "Item (by description)", list(catalogue),
            help="Type any part of a description or an item code to search.")
        scope_items = [catalogue[pick]]
    else:
        picks = st.multiselect(
            "Items (by description)", list(catalogue),
            help="Pick as many as you like. Leaving this empty would forecast "
                 "nothing, so at least one item is required.")
        scope_items = [catalogue[p] for p in picks]
        if not picks:
            st.info("Select at least one item, or switch to All materials.")

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
    elif scope_choice != "All materials" and not scope_items:
        st.error("Pick at least one item to forecast, or switch the scope to "
                 "All materials.")
    else:
        cfg = EngineConfig(
            scope={"item_codes": scope_items},
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
           "run picker at the top of the result pages, or delete ones you no "
           "longer need.")
runs = db.load_runs(db.stamp())
if runs.empty:
    st.info("No runs yet.")
else:
    display = pd.DataFrame({
        "Run": [db.run_label(r) for r in runs.itertuples()],
        "Status": runs["status"],
        "Series forecast": runs["n_series"],
        "Duration (s)": runs["duration_s"],
        "Data file": runs["source_name"],
    })
    ui.table(display,
             "Series forecast = how many item/line/output combinations this "
             "run covered. Duration is how long it took end to end.",
             hide_index=True)

    d1, d2 = st.columns(2)
    with d1:
        st.markdown("**Delete one run**")
        labels = {db.run_label(r): r.run_id for r in runs.itertuples()}
        to_delete = st.selectbox(
            "Run to delete", list(labels),
            help="Removes that run's forecasts, model choices and warnings. "
                 "Your data, model overrides and mode declarations are kept.")
        if st.button("🗑️ Delete this run",
                     help="Permanently removes the selected run. This cannot "
                          "be undone."):
            db.repo().delete_run(labels[to_delete])
            st.cache_data.clear()
            st.success(f"Deleted {to_delete}.")
            st.rerun()
    with d2:
        st.markdown("**Clear all history**")
        confirm = st.checkbox(
            f"Yes, delete all {len(runs)} run(s)",
            help="Tick to enable the button. Everything every run produced is "
                 "removed and run numbering restarts at 1; your data, model "
                 "overrides and mode declarations are kept.")
        if st.button("🗑️ Delete all run history", disabled=not confirm,
                     help="Permanently removes every run. This cannot be "
                          "undone."):
            removed = db.repo().delete_all_runs()
            st.cache_data.clear()
            st.success(f"Deleted {removed} run(s). Run numbering restarts "
                       "at 1.")
            st.rerun()
