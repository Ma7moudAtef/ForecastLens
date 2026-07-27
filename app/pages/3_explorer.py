"""Explorer — the primary planner screen.

Dimension picker with pure group-by semantics: an omitted dimension is simply
not in the group key. Selecting one atomic series opens the full detail view:
chart with intervals and driver overlay, intelligence card, model
competition table, plain-language reasoning, override control.
"""
import json

import pandas as pd
import streamlit as st

from app.components import charts, db
from core.forecast.aggregate import aggregate_forecasts, aggregate_observations

st.set_page_config(page_title="Explorer · ForecastLens", page_icon="🔍",
                   layout="wide")
st.title("🔍 Explorer")

run_id = db.pick_run(st)
if run_id is None:
    st.stop()

series = db.load_series(db.stamp())
selections = db.load_selections(db.stamp(), run_id)
forecasts = db.load_forecasts(db.stamp(), run_id)
observations = db.load_observations(db.stamp())

# --- dimension picker ---------------------------------------------------------
st.subheader("Dimension picker")
st.caption("Omit a dimension to combine across it. Combined rates are always "
           "driver-weighted (Σdemand ÷ Σdriver) — never averaged.")
c1, c2, c3 = st.columns(3)
with c1:
    items = st.multiselect("Items", sorted(series["item_code"].dropna().unique()))
with c2:
    lines = st.multiselect("Lines", sorted(series["line"].dropna().unique()))
with c3:
    outputs = st.multiselect("Output types",
                             sorted(series["output_type"].dropna().unique()))

split_dims = st.multiselect(
    "Split by", ["item_code", "line", "output_type"],
    default=["item_code", "line", "output_type"],
    help="Dimensions not selected here are combined across.")

filters = {"item_code": items, "line": lines, "output_type": outputs}

mask = pd.Series(True, index=series.index)
for dim, vals in filters.items():
    if vals:
        mask &= series[dim].isin(vals)
matched = series[mask]
st.caption(f"{len(matched)} atomic series match the current filters.")

# --- atomic detail when the selection resolves to exactly one series ----------
if len(matched) == 1 and set(split_dims) == {"item_code", "line", "output_type"}:
    row = matched.iloc[0]
    sid = row["series_id"]
    sel = selections[selections["series_id"] == sid]
    obs = observations[observations["series_id"] == sid].sort_values("period")
    fc = forecasts[forecasts["series_id"] == sid].sort_values("period")

    st.header(f"Series {sid}")
    if row["is_orphan"]:
        st.error("Orphan series: rate exists but its driver combination has "
                 "no record in any period. The rate forecast stands; demand "
                 "reconstruction is blocked until the planner resolves it.")

    is_relative = row["mode"] == "relative"
    value_col = "rate" if is_relative else "qty_base"
    std_rates = db.load_standard_rates(db.stamp())
    std = std_rates[(std_rates["item_code"] == row["item_code"]) &
                    (std_rates["line"] == row["line"]) &
                    (std_rates["output_type"] == row["output_type"])]
    std_rate = float(std["std_rate"].iloc[0]) if len(std) else None

    chart_fc = fc.rename(columns={"target_value": "value"})
    if is_relative:
        driver_overlay = obs[["period", "driver_qty"]].dropna()
        fig = charts.series_chart(
            obs.rename(columns={"rate": "value"}), chart_fc, "value", "value",
            driver=driver_overlay, std_rate=std_rate,
            title=f"Consumption rate — {row['target_uom'] or ''}")
    else:
        fig = charts.series_chart(
            obs.rename(columns={"qty_base": "value"}),
            fc.rename(columns={"reconstructed_demand": "value"})
              .assign(lower_80=fc["demand_lower_80"],
                      upper_80=fc["demand_upper_80"],
                      lower_95=fc["demand_lower_95"],
                      upper_95=fc["demand_upper_95"]),
            "value", "value",
            title=f"Quantity — {row['target_uom'] or ''}")
    st.plotly_chart(fig, width="stretch")

    col_card, col_reason = st.columns([1, 1])
    with col_card:
        st.subheader("Intelligence card")
        if len(sel):
            s = sel.iloc[0]
            conf = s["confidence_label"]
            icon = {"low": "🔴", "medium": "🟡", "high": "🟢"}.get(conf, "")
            st.markdown(
                f"**Mode:** {row['mode']} ({row['mode_source']})  \n"
                f"**Pattern:** {row['pattern_class']} "
                f"(ADI {row['adi']:.2f}, CV² {row['cv2']:.2f})" if pd.notna(row["adi"])
                else f"**Mode:** {row['mode']} ({row['mode_source']})  \n"
                     f"**Pattern:** {row['pattern_class']}")
            st.markdown(
                f"**History:** {row['n_observed']} observed / "
                f"{row['n_reliable']} usable of {row['n_periods']} periods  \n"
                f"**Trend strength:** {row['trend_strength'] if pd.notna(row['trend_strength']) else '–'} · "
                f"**Seasonality:** {row['seasonality_strength'] if pd.notna(row['seasonality_strength']) else '–'}  \n"
                f"**Data quality:** {row['data_quality']:.2f} · "
                f"**Forecastability:** {row['forecastability']:.2f}")
            st.markdown(
                f"**Selected model:** `{s['model_name']}`"
                + (f" (window {int(s['window'])})" if pd.notna(s["window"]) else "")
                + (" — planner override 🔒" if s["is_override"] else ""))
            st.markdown(f"**Confidence:** {icon} {conf} "
                        f"({s['confidence']:.2f})")
            if pd.notna(s["mase"]):
                st.markdown(f"**Validation MASE:** {s['mase']:.3f}")
        if pd.notna(row["structural_break_period"]):
            st.warning(f"Structural break detected around "
                       f"{row['structural_break_period']}.")

    with col_reason:
        st.subheader("Why this model")
        if len(sel):
            st.info(sel.iloc[0]["reason_text"])
            rejected = json.loads(sel.iloc[0]["rejected_json"] or "[]")
            if rejected:
                with st.expander(f"Why the other {len(rejected)} candidate(s) "
                                 "lost"):
                    for r in rejected:
                        st.markdown(f"- {r['reason']}")

    st.subheader("Model competition")
    val = db.load_validation(db.stamp(), run_id, sid)
    if val.empty:
        st.caption("No competition was run for this series (routed or "
                   "cold start) — see the reasoning above.")
    else:
        table = val[["model_name", "window", "mase", "mae", "rmse", "mape",
                     "smape", "n_origins", "status", "fail_reason"]].copy()
        table = table.sort_values("mase", na_position="last")
        st.caption("Ranked on MASE (scale-free). MAPE/sMAPE are display-only "
                   "— unreliable with zeros and small rates.")
        st.dataframe(table, width="stretch", hide_index=True)

    st.subheader("Override")
    st.caption("Pick a different model for this series; it stays locked "
               "across future runs until cleared.")
    model_options = sorted(val["model_name"].unique()) if not val.empty else \
        ["SBA", "TSB", "Croston", "ZeroForecast", "Naive"]
    oc1, oc2 = st.columns([1, 2])
    with oc1:
        override_model = st.selectbox("Model", model_options)
    with oc2:
        override_reason = st.text_input("Reason (required)", key="ov_reason")
    b1, b2 = st.columns(2)
    if b1.button("Lock override"):
        if not override_reason:
            st.error("A reason is required for the audit trail.")
        else:
            db.repo().set_model_override(sid, override_model, override_reason)
            st.success(f"{override_model} locked for {sid}. Takes effect on "
                       "the next run.")
    if b2.button("Clear override"):
        db.repo().clear_model_override(sid)
        st.success("Override cleared; automatic selection resumes next run.")

# --- aggregate view -----------------------------------------------------------
else:
    st.subheader("Aggregated view")
    agg_fc = aggregate_forecasts(forecasts, series, group_dims=split_dims,
                                 filters=filters)
    agg_obs = aggregate_observations(observations, series,
                                     group_dims=split_dims, filters=filters)
    if agg_fc.empty and agg_obs.empty:
        st.info("Nothing matches the current filters.")
        st.stop()

    group_cols = [d for d in split_dims]
    if group_cols:
        combos_fc = agg_fc[group_cols].drop_duplicates() if not agg_fc.empty \
            else agg_obs[group_cols].drop_duplicates()
        st.caption(f"{len(combos_fc)} group(s) from the current split.")
        labels = combos_fc.astype(str).agg(" · ".join, axis=1)
        choice = st.selectbox("Group", labels)
        chosen = combos_fc[labels == choice].iloc[0]
        m_fc = pd.Series(True, index=agg_fc.index)
        m_obs = pd.Series(True, index=agg_obs.index)
        for c in group_cols:
            m_fc &= agg_fc[c] == chosen[c]
            m_obs &= agg_obs[c] == chosen[c]
        g_fc, g_obs = agg_fc[m_fc], agg_obs[m_obs]
    else:
        g_fc, g_obs = agg_fc, agg_obs

    fig = charts.series_chart(
        g_obs.rename(columns={"qty_base": "value"}).sort_values("period"),
        g_fc.rename(columns={"demand": "value",
                             "demand_lower_80": "lower_80",
                             "demand_upper_80": "upper_80",
                             "demand_lower_95": "lower_95",
                             "demand_upper_95": "upper_95"})
            .sort_values("period"),
        "value", "value",
        title="Combined demand (Σ atomic demand; interval bounds summed — "
              "approximate)")
    st.plotly_chart(fig, width="stretch")

    if not g_fc.empty and g_fc["rate"].notna().any():
        st.caption("Combined rate shown below is driver-weighted "
                   "(Σdemand ÷ Σdriver).")
    show_cols = ["period", *group_cols, "demand", "driver_plan", "rate",
                 "n_series", "confidence"]
    st.dataframe(g_fc[[c for c in show_cols if c in g_fc.columns]],
                 width="stretch", hide_index=True)
