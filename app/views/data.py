"""Data — the default workbook is preloaded; review it, edit it in place,
or bring your own file."""
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

import pandas as pd
import streamlit as st

from app.components import (datacache, db, filebrowser, items as item_utils,
                            paths, samples, tables, ui)
from core.analyze.statistics import analyze_all
from core.config import AppConfig, EngineConfig
from core.io.excel_source import ExcelSource
from core.prep.series_builder import build_series
from core.validate import rules

st.title("🗂️ Data")

app_cfg = AppConfig()
cfg = EngineConfig()

SHEET_HELP = {
    "bom": "Item master: one row per item — code, description, unit, price, "
           "weight and category levels. The optional 'mode' column lets you "
           "declare an item Relative or Absolute.",
    "consumption": "Consumption history: what was consumed, when, on which "
                   "line, for which output. A cons_rate value marks the item "
                   "as driver-dependent (Relative).",
    "prod": "The driver table (production output). production_qty1 is the "
            "driver quantity; production_type separates 'actual' history "
            "from the future 'plan'. May be empty for trading businesses.",
    "consumption_figs": "Engineered standard consumption rates per item, "
                        "line and output — used as a forecast anchor and as "
                        "an actual-vs-standard benchmark.",
    "context_calendar": "Optional. Things you know in advance that the "
                        "driver table cannot express: promotions, campaigns, "
                        "shutdowns, recipe changes. One row per factor per "
                        "period; leave unit and stream blank for something "
                        "plant-wide. Fill in future periods too — a factor "
                        "the engine cannot read for the periods it is "
                        "forecasting is history, not a forecasting input.",
}

# --- source -------------------------------------------------------------------
ui.section("Data source",
           "Where the app reads your input workbook. The bundled default "
           "workbook is already loaded, so you can explore immediately. Any "
           "edit you save creates your own working copy and leaves the "
           "bundled file untouched.")

bundled = paths.bundled_sample()
working = paths.working_workbook()
active = st.session_state.get("input_path") or (
    str(paths.default_input_path()) if paths.default_input_path() else "")

DEFAULT_OPT = "📦 Default workbook (preloaded)"
WORKING_OPT = "✏️ My working copy (saved edits)"
UPLOAD_OPT = "⬆️ Upload a file"
PATH_OPT = "📂 A file on this computer"

options = [DEFAULT_OPT]
if working.exists():
    options.append(WORKING_OPT)
options += [UPLOAD_OPT, PATH_OPT]

# The choice is sticky: once the user picks a source it stays picked until
# they change it themselves — switching pages or saving an edit must never
# silently drop them back onto the default workbook.
remembered = st.session_state.get("data_source_choice", DEFAULT_OPT)
if remembered not in options:
    remembered = DEFAULT_OPT
choice = st.radio(
    "Which data should the app use?", options,
    index=options.index(remembered), horizontal=True,
    help="Default = the sample workbook shipped with the app. Working copy = "
         "your edited version. Upload = send a file to the app. On this "
         "computer = point at a path, with a folder browser. Your choice is "
         "remembered until you change it.")
st.session_state["data_source_choice"] = choice

if choice == DEFAULT_OPT and bundled:
    active = str(bundled)
elif choice == WORKING_OPT:
    active = str(working)
elif choice == UPLOAD_OPT:
    uploaded = st.file_uploader(
        "Excel workbook (sheets: bom, consumption, prod, consumption_figs, "
        "and optionally context_calendar)",
        type=[e.lstrip(".") for e in app_cfg.allowed_upload_extensions],
        key="data_upload",
        help="Only .xlsx is accepted. The file is checked against the "
             "expected schema before anything is processed.")
    if uploaded is not None:
        if uploaded.size > app_cfg.max_upload_mb * 1024 * 1024:
            st.error(f"File exceeds the {app_cfg.max_upload_mb} MB cap.")
        else:
            tmp = Path(tempfile.gettempdir()) / "forecastlens_upload.xlsx"
            tmp.write_bytes(uploaded.getvalue())
            st.session_state["uploaded_path"] = str(tmp)
            active = str(tmp)
    elif st.session_state.get("uploaded_path"):
        # keep the previously uploaded file across page switches
        active = st.session_state["uploaded_path"]
else:
    col_path, col_browse = st.columns([4, 1])
    with col_path:
        typed = st.text_input(
            "Workbook path", value=st.session_state.get("typed_path", active),
            help="Full path to an .xlsx file on the machine running the app.")
    with col_browse:
        st.write("")
        picked = filebrowser.path_picker("data_browse")
    active = picked or typed
    st.session_state["typed_path"] = active

if not active or not Path(active).exists():
    st.warning("No readable workbook selected yet.")
    st.stop()

st.session_state["input_path"] = active
st.caption(f"Active file: `{active}`")

col_dl, _ = st.columns([1, 2])
with col_dl:
    if bundled:
        st.download_button(
            "⬇️ Download sample (10 rows + data dictionary)",
            samples.build_sample_workbook(bundled),
            file_name="forecastlens_sample.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="A small extract of every sheet plus a data_dictionary sheet "
                 "explaining what each column means and how the engine uses "
                 "it. Use it as the template for your own data.")


def _compute_analysis(p: str, overrides: dict[str, str]):
    raw = ExcelSource(p).load()
    warnings = rules.run_all(raw, cfg)
    prep = build_series(raw, cfg, mode_overrides=overrides)
    analyzed = analyze_all(prep, cfg)
    wdf = pd.DataFrame([{
        "severity": w.severity.value, "code": w.code, "scope": w.scope(),
        "count": w.count, "message": w.message}
        for w in warnings + prep.warnings])
    summary = {
        "consumption_rows": len(raw.consumption),
        "items": raw.consumption["item_code"].nunique(),
        "driver_rows": len(raw.driver),
        "date_min": str(raw.consumption["date"].min().date()),
        "date_max": str(raw.consumption["date"].max().date()),
    }
    return summary, wdf, analyzed, raw.items


@st.cache_data(show_spinner=False)
def _analyze(p: str, key: str, overrides: dict[str, str]):
    """Session cache in front of the on-disk cache, so the workbook is read
    and validated once per machine rather than once per app start."""
    return datacache.get_or_compute(key, lambda: _compute_analysis(p, overrides))


mode_overrides = {r.item_code: r.mode
                  for r in db.repo().get_mode_overrides().itertuples()}
cache_key = datacache.fingerprint(Path(active), cfg, mode_overrides)
with st.spinner("Reading and validating the workbook…"):
    (summary, warnings_df, analyzed, bom_items), from_cache = _analyze(
        active, cache_key, mode_overrides)
desc_lookup = item_utils.description_lookup(bom_items)

cache_note = st.columns([3, 1])
with cache_note[1]:
    if from_cache:
        st.caption("⚡ loaded from cache")
    if st.button("↻ Re-read file", key="refresh_analysis",
                 help="Read and validate the workbook again from scratch. "
                      "Normally unnecessary — the cached result is reused "
                      "only while the file, the settings and your mode "
                      "declarations are unchanged."):
        datacache.clear()
        st.cache_data.clear()
        st.rerun()

tabs = st.tabs(["📊 Summary", "⚠️ Validation", "📋 bom", "📈 consumption",
                "🏭 prod", "📐 consumption_figs", "🗓️ context_calendar",
                "🏷️ Item modes"])

# --- summary ------------------------------------------------------------------
with tabs[0]:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Consumption rows", f"{summary['consumption_rows']:,}",
              help="Total history rows read from the consumption sheet.")
    c2.metric("Items", summary["items"],
              help="Distinct item codes that appear in the history.")
    c3.metric("Forecast series", len(analyzed),
              help="Atomic forecasting units — one per item + line + output "
                   "type combination. Each is fitted separately.")
    c4.metric("Driver rows", f"{summary['driver_rows']:,}",
              help="Rows in the driver (production) table, actual and plan.")
    c5.metric("Coverage", f"{summary['date_min']} → {summary['date_max']}",
              help="First and last period present in the history.")

    col_a, col_b = st.columns(2)
    with col_a:
        ui.section("Mode split",
                   "How many items are driver-dependent (Relative) versus "
                   "independent (Absolute). Mode is a property of the "
                   "material's nature: a Relative item never flips to "
                   "Absolute just because driver data is missing.")
        st.bar_chart(analyzed.groupby("mode")["item_code"].nunique())
    with col_b:
        ui.section("Demand pattern classes",
                   "Smooth = moves every period, steady sizes. Erratic = "
                   "moves every period, wild sizes. Intermittent = many zero "
                   "periods. Lumpy = both. Too short = not enough history to "
                   "classify. Intermittent and lumpy items are routed to the "
                   "sporadic-demand models instead of a competition.")
        st.bar_chart(analyzed["pattern_class"].value_counts())

    orphans = analyzed[analyzed["is_orphan"] == 1]
    if not orphans.empty:
        st.error(
            f"**{len(orphans)} orphan series need your decision.** These have "
            "a consumption rate but no driver record exists for their (line, "
            "output) in any period — the denominator does not exist. They "
            "stay Relative and are excluded from demand reconstruction; no "
            "denominator is guessed and nothing is deleted. Either add driver "
            "rows for the combination in the **prod** tab, or declare the "
            "item Absolute in the **Item modes** tab.")
        show = orphans[["item_code", "line", "output_type", "mode",
                        "n_observed"]].copy()
        show.insert(1, "description",
                    show["item_code"].map(lambda c: desc_lookup.get(str(c), "")))
        ui.table(show, "Every orphan series, shown by item code and "
                       "description with its line and output type.",
                 hide_index=True)

# --- validation ---------------------------------------------------------------
with tabs[1]:
    ui.section("Validation report",
               "Everything the engine noticed about your data. Nothing is "
               "ever deleted automatically: issues are flagged so you decide. "
               "Only 'fatal' issues stop a run.")
    if warnings_df.empty:
        st.success("No issues found.")
    else:
        sev_order = ["fatal", "warning", "info"]
        sev_tabs = st.tabs([f"{s} ({(warnings_df['severity'] == s).sum()})"
                            for s in sev_order])
        for tab, sev in zip(sev_tabs, sev_order):
            with tab:
                sub = warnings_df[warnings_df["severity"] == sev]
                if sub.empty:
                    st.write("None.")
                else:
                    ui.table(sub[["code", "scope", "count", "message"]],
                             "code = issue type, scope = which item/series it "
                             "affects, count = how many rows or periods, "
                             "message = what it means and what the engine did.",
                             hide_index=True)
        if (warnings_df["severity"] == "fatal").any():
            st.error("Fatal issues block the run. Fix the workbook first.")
        else:
            st.success("No fatal issues — a run may proceed.")

# --- editable sheets ----------------------------------------------------------
_frames = paths.read_workbook_sheets(Path(active))


def _save(frames: dict[str, pd.DataFrame], note: str) -> None:
    paths.write_workbook(frames, working)
    st.session_state["input_path"] = str(working)
    # saving IS the user choosing their working copy — move the selector
    # there rather than letting the next rerun snap back to the default
    st.session_state["data_source_choice"] = WORKING_OPT
    st.cache_data.clear()
    st.success(f"{note} Saved to your working copy: `{working}`")


def _sheet_tab(sheet: str, container) -> None:
    with container:
        ui.section(f"{sheet}", SHEET_HELP[sheet])
        current = _frames.get(sheet, pd.DataFrame())
        if current.empty:
            st.info(f"The '{sheet}' sheet is empty or absent in this file. "
                    "You can still add rows below and save.")
        st.caption(f"{len(current):,} row(s). Edit cells directly, add rows "
                   "with the ➕ row at the bottom, or select rows and press "
                   "delete to remove them.")
        edited = st.data_editor(
            current, num_rows="dynamic", width="stretch",
            key=f"editor_{sheet}", height=380)

        col_save, col_reset = st.columns([1, 3])
        with col_save:
            if st.button("💾 Save table", key=f"save_{sheet}",
                         help="Write your edits to your own working copy of "
                              "the workbook. The bundled default file is "
                              "never modified. Takes effect on the next run."):
                frames = dict(_frames)
                frames[sheet] = edited
                _save(frames, f"'{sheet}' updated.")
        with col_reset:
            st.caption("Edits are saved to a working copy — the original file "
                       "is never overwritten.")

        with st.expander(f"➕ Import rows into '{sheet}' — extend or replace",
                         expanded=False):
            st.caption("Bring in rows from another file. **Extend** appends "
                       "them to what is already here; **Replace** discards "
                       "the current table and uses the imported rows instead.")
            up = st.file_uploader(
                f"File with {sheet} rows (.xlsx or .csv)",
                type=["xlsx", "csv"], key=f"imp_{sheet}",
                help="Column names must match this table's columns. Extra "
                     "columns are ignored; missing ones become empty.")
            mode = st.radio(
                "How should the imported rows be applied?",
                ["Extend — add to existing rows",
                 "Replace — discard existing rows"],
                key=f"mode_{sheet}", horizontal=False,
                help="Extend keeps your current data and appends. Replace "
                     "swaps the whole table for the imported one.")
            if up is not None:
                try:
                    incoming = (pd.read_csv(up) if up.name.lower().endswith(".csv")
                                else pd.read_excel(up, engine="openpyxl"))
                except Exception as exc:
                    st.error(f"Could not read that file: {exc}")
                    incoming = None
                if incoming is not None:
                    st.caption(f"Preview — {len(incoming):,} row(s) incoming:")
                    ui.table(incoming.head(10),
                             "The first rows of the file you are importing.",
                             hide_index=True)
                    unknown = tables.unknown_columns(current, incoming)
                    if unknown:
                        st.warning(f"Columns not in this table (ignored): "
                                   f"{unknown}")
                    if st.button("Apply import", key=f"apply_{sheet}",
                                 type="primary",
                                 help="Apply the imported rows using the "
                                      "Extend/Replace choice above and save "
                                      "to your working copy."):
                        import_mode = (tables.ImportMode.EXTEND
                                       if mode.startswith("Extend")
                                       else tables.ImportMode.REPLACE)
                        result = tables.apply_import(current, incoming,
                                                     import_mode)
                        note = (f"Added {len(incoming):,} row(s) to '{sheet}'."
                                if import_mode is tables.ImportMode.EXTEND
                                else f"'{sheet}' replaced with "
                                     f"{len(incoming):,} row(s).")
                        frames = dict(_frames)
                        frames[sheet] = result
                        _save(frames, note)
                        st.rerun()


for sheet, tab in zip(paths.SHEET_ORDER, tabs[2:7]):
    _sheet_tab(sheet, tab)

# --- item modes ---------------------------------------------------------------
with tabs[7]:
    ui.section("Declare an item's mode",
               "Tell the engine that a material is driver-dependent "
               "(Relative) or independent (Absolute), regardless of what the "
               "recorded data suggests. Your declaration always wins, and it "
               "stays until you clear it.")
    labels = item_utils.build_labels(analyzed["item_code"].unique(), desc_lookup)
    col1, col2, col3 = st.columns([2, 1, 2])
    with col1:
        picked_label = st.selectbox(
            "Item (by description)", list(labels),
            help="Items are listed by description, with the item code after "
                 "the dash. Type to search either one.")
    with col2:
        mode_choice = st.selectbox(
            "Mode", ["relative", "absolute"],
            help="Relative = consumption depends on production output, so "
                 "the engine forecasts a rate. Absolute = consumption is "
                 "independent, so it forecasts the quantity directly.")
    with col3:
        reason = st.text_input(
            "Reason (recorded)",
            help="Stored with the declaration so future users know why this "
                 "item was overridden.")
    if st.button("Declare mode",
                 help="Save the declaration. It applies from the next run."):
        db.repo().set_mode_override(labels[picked_label], mode_choice, reason)
        st.success(f"{picked_label} declared {mode_choice}. Takes effect on "
                   "the next run.")
        st.cache_data.clear()

    existing = db.repo().get_mode_overrides()
    if not existing.empty:
        shown = existing.copy()
        shown.insert(1, "description",
                     shown["item_code"].map(lambda c: desc_lookup.get(str(c), "")))
        ui.table(shown, "Declarations currently in force.", hide_index=True)
        clear_labels = item_utils.build_labels(existing["item_code"], desc_lookup)
        clear_pick = st.selectbox(
            "Clear a declaration", list(clear_labels),
            help="Remove a declaration so the engine goes back to inferring "
                 "the mode from the data.")
        if st.button("Clear declaration",
                     help="Delete the selected declaration."):
            db.repo().clear_mode_override(clear_labels[clear_pick])
            st.cache_data.clear()
            st.rerun()
