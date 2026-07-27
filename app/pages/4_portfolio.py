"""Portfolio — the triage screen. 820 series in one table, shrunk to the
handful a planner actually needs to look at."""
import streamlit as st

from app.components import auth, badges, db

st.set_page_config(page_title="Portfolio · ForecastLens", page_icon="📋",
                   layout="wide")
auth.require_secret()
st.title("📋 Portfolio")

run_id = db.pick_run(st)
if run_id is None:
    st.stop()

series = db.load_series(db.stamp())
selections = db.load_selections(db.stamp(), run_id)
accuracy = db.load_accuracy(db.stamp())

badge = badges.recommend(series, selections, accuracy)
table = series.merge(
    selections[["series_id", "model_name", "window", "mase", "confidence",
                "confidence_label", "is_override", "route"]],
    on="series_id", how="left")
table["recommendation"] = table["series_id"].map(badge).map(badges.badge_label)

# --- summary tiles ------------------------------------------------------------
counts = badge.value_counts()
cols = st.columns(len(badges.BADGES))
for col, (key, label) in zip(cols, badges.BADGES.items()):
    col.metric(label, int(counts.get(key, 0)))

st.caption("Priority: data quality → structural change → confidence "
           "declining → manual review → OK. Start at the left-most non-zero "
           "column.")

# --- filters ------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
with c1:
    f_badge = st.multiselect("Recommendation",
                             list(badges.BADGES.values()))
with c2:
    f_mode = st.multiselect("Mode", ["relative", "absolute"])
with c3:
    f_class = st.multiselect("Pattern",
                             sorted(series["pattern_class"].dropna().unique()))
with c4:
    f_conf = st.multiselect("Confidence", ["low", "medium", "high"])

view = table
if f_badge:
    view = view[view["recommendation"].isin(f_badge)]
if f_mode:
    view = view[view["mode"].isin(f_mode)]
if f_class:
    view = view[view["pattern_class"].isin(f_class)]
if f_conf:
    view = view[view["confidence_label"].isin(f_conf)]

sort_by = st.selectbox("Sort by", ["confidence", "mase", "data_quality",
                                   "n_reliable", "series_id"])
view = view.sort_values(sort_by, na_position="last")

show = view[["series_id", "recommendation", "mode", "pattern_class",
             "model_name", "confidence_label", "confidence", "mase",
             "data_quality", "n_observed", "n_reliable", "is_orphan",
             "structural_break_period", "is_override"]]
st.dataframe(show, width="stretch", hide_index=True, height=520)
st.caption(f"{len(view)} of {len(table)} series shown. Open any series in "
           "the Explorer for the full picture.")

st.download_button(
    "Download this view (CSV)",
    show.to_csv(index=False).encode(),
    file_name="portfolio.csv", mime="text/csv")
