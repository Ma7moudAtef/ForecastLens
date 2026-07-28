"""Explorer — the primary planner screen.

Items are picked by description. Results are shown by item code,
description, line and output type as separate columns — the internal series
identifier never appears. For Relative items the forecast chart shows the
consumption rate (cons_rate), with an optional reconstructed-demand view.
"""
# --- path bootstrap ----------------------------------------------------------
# Make the repo root importable no matter how this script is launched:
# `streamlit run`, Streamlit Community Cloud, the frozen exe, or tests.
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# -----------------------------------------------------------------------------
import json

import pandas as pd
import streamlit as st

from app.components import charts, db, items as item_utils, ui
from core.forecast.aggregate import aggregate_forecasts, aggregate_observations

st.title("🔍 Explorer")

run_id = db.pick_run(st)
if run_id is None:
    st.stop()

all_series = db.load_series(db.stamp())
selections = db.load_selections(db.stamp(), run_id)
forecasts = db.load_forecasts(db.stamp(), run_id)
observations = db.load_observations(db.stamp())
bom_items = db.load_items(db.stamp())
desc_lookup = item_utils.description_lookup(bom_items)

# A run may have been scoped to some items only — offer what it produced.
series = all_series[all_series["series_id"].isin(selections["series_id"])]
if series.empty:
    st.warning("This run produced no results.")
    st.stop()
if len(series) < len(all_series):
    st.caption(f"This run covered {len(series)} of {len(all_series)} series "
               "— the others were not part of its scope.")

# --- pickers ------------------------------------------------------------------
ui.section("Choose what to look at",
           "Pick items by description (the code is shown after the dash). "
           "Anything you leave empty is combined across: no line selected "
           "means every line added together, not listed separately. Narrow "
           "it down to a single item, line and output to open that series' "
           "full detail.")
c1, c2, c3 = st.columns(3)
with c1:
    item_labels = item_utils.build_labels(
        series["item_code"].dropna().unique(), desc_lookup)
    picked_labels = st.multiselect(
        "Items (by description)", list(item_labels),
        help="Type any part of a description or a code to search. Leave "
             "empty to include every item.")
    picked_items = [item_labels[l] for l in picked_labels]
with c2:
    lines = st.multiselect(
        "Production lines", sorted(series["line"].dropna().unique()),
        help="Which lines to include. Empty = all lines combined together.")
with c3:
    outputs = st.multiselect(
        "Output types", sorted(series["output_type"].dropna().unique()),
        help="Which outputs (products) to include. Empty = all outputs "
             "combined together.")

filters = {"item_code": picked_items, "line": lines, "output_type": outputs}
mask = pd.Series(True, index=series.index)
for dim, vals in filters.items():
    if vals:
        mask &= series[dim].isin(vals)
matched = series[mask]
if len(matched) == 1:
    st.caption("1 forecast series selected — showing its full detail.")
else:
    st.caption(f"{len(matched)} forecast series selected — shown combined. "
               "Narrow the selection to a single item, line and output to "
               "see one series in full.")

# --- single-series detail -----------------------------------------------------
if len(matched) == 1:
    row = matched.iloc[0]
    sid = row["series_id"]
    description = desc_lookup.get(str(row["item_code"]), "")
    sel = selections[selections["series_id"] == sid]
    obs = observations[observations["series_id"] == sid].sort_values("period")
    fc = forecasts[forecasts["series_id"] == sid].sort_values("period")

    st.header(description or str(row["item_code"]))
    id1, id2, id3, id4 = st.columns(4)
    id1.metric("Item code", str(row["item_code"]),
               help="The item's code in your master data.")
    id2.metric("Description", description or "—",
               help="The item's description from the bom sheet.")
    id3.metric("Production line", str(row["line"] or "—"),
               help="The line this forecast is for.")
    id4.metric("Output type", str(row["output_type"] or "—"),
               help="The product/output this forecast is for.")

    if row["is_orphan"]:
        st.error("This item has a consumption rate but no driver record for "
                 "its line and output in any period — the denominator does "
                 "not exist. The rate forecast below stands; demand in units "
                 "cannot be reconstructed until driver data is added or the "
                 "item is declared Absolute on the Data page.")

    is_relative = row["mode"] == "relative"
    std_rates = db.load_standard_rates(db.stamp())
    std = std_rates[(std_rates["item_code"] == row["item_code"]) &
                    (std_rates["line"] == row["line"]) &
                    (std_rates["output_type"] == row["output_type"])]
    std_rate = float(std["std_rate"].iloc[0]) if len(std) else None

    if is_relative:
        view = st.radio(
            "Chart shows", ["Consumption rate (cons_rate)",
                            "Reconstructed demand (rate × planned driver)"],
            horizontal=True,
            help="This is a Relative item, so the engine forecasts its "
                 "consumption RATE — that is the modelled quantity and the "
                 "default view. Reconstructed demand multiplies that rate by "
                 "your production plan to get units.")
        if view.startswith("Consumption rate"):
            fig = charts.series_chart(
                obs.rename(columns={"rate": "value"}),
                fc.rename(columns={"target_value": "value"}),
                "value", "value",
                driver=obs[["period", "driver_qty"]].dropna(),
                std_rate=std_rate,
                title=f"Consumption rate (cons_rate) — {row['target_uom'] or ''}")
            chart_help = (
                "Blue = the consumption rate actually recorded each period. "
                "Red dashed = the forecast rate. Shaded bands = the 80% and "
                "95% ranges the rate is expected to fall in. Grey dotted = "
                "the production driver. Green line = your engineered "
                "standard rate, if one exists.")
        else:
            fig = charts.series_chart(
                obs.rename(columns={"qty_base": "value"}),
                fc.rename(columns={"reconstructed_demand": "value"})
                  .assign(lower_80=fc["demand_lower_80"],
                          upper_80=fc["demand_upper_80"],
                          lower_95=fc["demand_lower_95"],
                          upper_95=fc["demand_upper_95"]),
                "value", "value",
                title=f"Reconstructed demand — {row['target_uom'] or ''}")
            chart_help = (
                "The forecast rate multiplied by the planned production "
                "driver for each future period, giving expected demand in "
                "units. Gaps mean no production plan exists for that period.")
    else:
        fig = charts.series_chart(
            obs.rename(columns={"qty_base": "value"}),
            fc.rename(columns={"reconstructed_demand": "value"})
              .assign(lower_80=fc["demand_lower_80"],
                      upper_80=fc["demand_upper_80"],
                      lower_95=fc["demand_lower_95"],
                      upper_95=fc["demand_upper_95"]),
            "value", "value",
            title=f"Consumption quantity — {row['target_uom'] or ''}")
        chart_help = (
            "Blue = quantity actually consumed each period. Red dashed = the "
            "forecast. Shaded bands = the 80% and 95% ranges. This is an "
            "Absolute item: it is modelled per day and multiplied back by "
            "each period's length, so a short February is never mistaken for "
            "a drop in demand.")
    ui.chart(fig, chart_help)

    col_card, col_reason = st.columns(2)
    with col_card:
        ui.section("Intelligence card",
                   "Everything the engine worked out about this item's "
                   "behaviour, and how much to trust the forecast.")
        if len(sel):
            s = sel.iloc[0]
            conf = s["confidence_label"]
            icon = {"low": "🔴", "medium": "🟡", "high": "🟢"}.get(conf, "")
            pattern = row["pattern_class"]
            if pd.notna(row["adi"]):
                pattern += (f" (moves every {row['adi']:.1f} periods on "
                            f"average)")
            st.markdown(
                f"**Mode:** {row['mode']} ({row['mode_source']})  \n"
                f"**Demand pattern:** {pattern}  \n"
                f"**History:** {row['n_observed']} periods recorded, "
                f"{row['n_reliable']} usable for fitting  \n"
                f"**Data quality:** {row['data_quality']:.2f} · "
                f"**Forecastability:** {row['forecastability']:.2f}")
            n_applicable = row.get("n_applicable")
            if pd.notna(n_applicable) and n_applicable < row["n_periods"]:
                skipped = int(row["n_periods"] - n_applicable)
                st.caption(
                    f"{skipped} period(s) had no production on this line at "
                    "all, so they are not counted as zero demand — the line "
                    "simply did not run.")
            st.markdown(
                f"**Selected model:** `{s['model_name']}`"
                + (f" (window {int(s['window'])})" if pd.notna(s["window"]) else "")
                + (" — your override 🔒" if s["is_override"] else ""))
            st.markdown(f"**Confidence:** {icon} {conf} "
                        f"({s['confidence']:.2f})")
            ui.help_icon(
                "Confidence combines back-tested accuracy with how much "
                "usable history exists, how predictable the item is, and "
                "data quality — so a short series can never look highly "
                "trustworthy just because its interval is narrow.")
        if pd.notna(row["structural_break_period"]):
            st.warning(f"Behaviour appears to have shifted around "
                       f"{row['structural_break_period']} — worth checking "
                       "whether something changed in the process.")

    with col_reason:
        ui.section("Why this model",
                   "The engine's reasoning in plain language: why the winner "
                   "was chosen and why each alternative was not.")
        if len(sel):
            st.info(sel.iloc[0]["reason_text"])
            rejected = json.loads(sel.iloc[0]["rejected_json"] or "[]")
            if rejected:
                with st.expander(f"Why the other {len(rejected)} candidate(s) "
                                 "lost"):
                    for r in rejected:
                        st.markdown(f"- {r['reason']}")

    ui.section("Model competition",
               "Every model that was back-tested on this item's own history, "
               "best first. Ranked on MASE — a scale-free error measure that "
               "stays meaningful with zero periods and very small rates. "
               "MAPE and sMAPE are shown for reference only; they are "
               "unreliable here.")
    val = db.load_validation(db.stamp(), run_id, sid)
    if val.empty:
        st.caption("No competition was run for this item — it was either "
                   "routed to the sporadic-demand models or is too new to "
                   "back-test. The reasoning above explains which applies.")
    else:
        table = val[["model_name", "window", "mase", "mae", "rmse", "mape",
                     "smape", "n_origins", "status", "fail_reason"]].copy()
        ui.table(table.sort_values("mase", na_position="last"),
                 "mase = ranking error (lower is better); n_origins = how "
                 "many back-test windows it was scored on; status shows "
                 "models that could not be fitted or validated.",
                 hide_index=True)

    ui.section("Override the chosen model",
               "If you know something the data does not, pick a different "
               "model. It stays locked for this item across future runs "
               "until you clear it, and your reason is recorded.")
    model_options = sorted(val["model_name"].unique()) if not val.empty else \
        ["SBA", "TSB", "Croston", "ZeroForecast", "Naive"]
    oc1, oc2 = st.columns([1, 2])
    with oc1:
        override_model = st.selectbox(
            "Model", model_options,
            help="Any model that was available to this item.")
    with oc2:
        override_reason = st.text_input(
            "Reason (required)", key="ov_reason",
            help="Recorded with the override so the decision is auditable.")
    b1, b2 = st.columns(2)
    if b1.button("🔒 Lock override",
                 help="Force this model for this item from the next run on."):
        if not override_reason:
            st.error("A reason is required for the audit trail.")
        else:
            db.repo().set_model_override(sid, override_model, override_reason)
            st.success(f"{override_model} locked. Takes effect on the next run.")
    if b2.button("Clear override",
                 help="Remove the lock and let the engine choose again."):
        db.repo().clear_model_override(sid)
        st.success("Override cleared; automatic selection resumes next run.")

# --- aggregated view ----------------------------------------------------------
else:
    ui.section("Combined view",
               "Everything you selected, added together. Relative items are "
               "shown as a consumption rate, each period weighted by the "
               "production it was consumed against — never a plain average "
               "of rates. Absolute items are shown as consumption quantity. "
               "A rate and a quantity cannot share an axis, so pick one at a "
               "time.")

    # Rates and quantities are different units and must never be mixed into
    # one number. Split the selection by mode and chart one mode at a time.
    matched_modes = sorted(matched["mode"].unique())
    if len(matched_modes) > 1:
        counts = matched["mode"].value_counts()
        mode_labels = {
            "relative": f"Relative — consumption rate ({counts.get('relative', 0)} series)",
            "absolute": f"Absolute — consumption quantity ({counts.get('absolute', 0)} series)",
        }
        chosen_label = st.radio(
            "Show", [mode_labels[m] for m in matched_modes], horizontal=True,
            key="combined_mode",
            help="Your selection mixes driver-dependent (Relative) and "
                 "independent (Absolute) items. A rate and a quantity cannot "
                 "be added together or plotted on one axis, so choose which "
                 "to view.")
        view_mode = next(m for m in matched_modes
                         if mode_labels[m] == chosen_label)
    else:
        view_mode = matched_modes[0]

    mode_series = series[series["mode"] == view_mode]
    is_relative_view = view_mode == "relative"

    # Everything selected is combined into one series — what the picker
    # leaves empty is what gets combined across. There is no second grouping
    # control: the picker alone decides what you are looking at.
    g_fc = aggregate_forecasts(forecasts, mode_series, group_dims=[],
                               filters=filters)
    g_obs = aggregate_observations(observations, mode_series, group_dims=[],
                                   filters=filters)
    if g_fc.empty and g_obs.empty:
        st.info("Nothing matches the current selection.")
        st.stop()

    if is_relative_view:
        # Σ(rate·driver) ÷ Σdriver — the driver-weighted mean of the recorded
        # rates. History and forecast are computed the same way, so the two
        # halves of this chart are on one scale and directly comparable.
        rated = g_fc[g_fc["rate"].notna()]
        dropped = len(g_fc) - len(rated)
        if dropped:
            st.caption(
                f"{dropped} forecast period(s) are not charted: no production "
                "plan covers them, so no combined rate can be formed. Series "
                "whose history ends early forecast into periods your plan "
                "does not reach.")
        fig = charts.series_chart(
            g_obs.rename(columns={"rate": "value"}).sort_values("period"),
            rated.rename(columns={"rate": "value"}).sort_values("period"),
            "value", "value",
            driver=(g_obs[["period", "driver_qty"]].dropna()
                    if "driver_qty" in g_obs.columns else None),
            title="Combined consumption rate (cons_rate)")
        chart_help = (
            "The consumption rate for this group, in the same units as the "
            "cons_rate in your data. Each period's rate is weighted by the "
            "production it was consumed against — a driver-weighted average, "
            "never a plain average of rates. History and forecast are "
            "calculated the same way, so they are directly comparable. Grey "
            "dotted line is the production itself, counted once per line "
            "rather than once per item. Prediction bands are not shown: "
            "summed bounds do not divide into a meaningful rate interval.")
    else:
        fig = charts.series_chart(
            g_obs.rename(columns={"qty_base": "value"}).sort_values("period"),
            g_fc.rename(columns={"demand": "value",
                                 "demand_lower_80": "lower_80",
                                 "demand_upper_80": "upper_80",
                                 "demand_lower_95": "lower_95",
                                 "demand_upper_95": "upper_95"})
                .sort_values("period"),
            "value", "value", title="Combined consumption quantity")
        chart_help = (
            "History and forecast consumption quantity for every series in "
            "this group, added together. Interval bounds are summed too, "
            "which is a conservative approximation — it assumes the "
            "individual errors move together.")
    ui.chart(fig, chart_help)

    value_cols = (["rate", "demand", "driver_plan"] if is_relative_view
                  else ["demand", "driver_plan", "rate"])
    cols = ["period"] + [c for c in value_cols + ["n_series", "confidence"]
                         if c in g_fc.columns]
    ui.table(g_fc[cols],
             "One row per future period for everything you selected, "
             "combined. demand = forecast units. driver_plan = planned "
             "production for the period, counted once per line rather than "
             "once per item. rate = the driver-weighted average of the "
             "member rates, in your data's own cons_rate units — never a "
             "plain average. n_series = how many item/line/output "
             "combinations are behind the row.", hide_index=True)
