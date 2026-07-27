"""ForecastLens — home page. All computation happens in core.pipeline;
every page here only reads completed results from SQLite."""
import streamlit as st

from app.components import auth, db

st.set_page_config(page_title="ForecastLens", page_icon="📈", layout="wide")
auth.require_secret()

st.title("📈 ForecastLens")
st.caption("Adaptive consumption forecasting with plain-language reasoning")

runs = db.load_runs(db.stamp())
series = db.load_series(db.stamp())

col1, col2, col3, col4 = st.columns(4)
col1.metric("Completed runs", int((runs["status"] == "complete").sum())
            if not runs.empty else 0)
col2.metric("Series", len(series))
if not series.empty:
    col3.metric("Relative / Absolute",
                f"{(series['mode'] == 'relative').sum()} / "
                f"{(series['mode'] == 'absolute').sum()}")
    col4.metric("Orphan series", int(series["is_orphan"].sum()))

st.markdown("""
**Workflow**

1. **Data** — load a workbook, review the validation report, resolve flagged
   issues (including any orphan series), optionally declare an item's mode.
2. **Configure & Run** — set the horizon and model toggles, launch the batch.
3. **Explorer** — inspect any series or combination: chart, intelligence
   card, model competition, plain-language reasoning, override control.
4. **Portfolio** — triage: which series actually need attention.
5. **Accuracy** — import actuals, track forecast error over time.
6. **Export** — Excel/CSV of forecasts, selections and warnings.

Every forecast carries a confidence and a reason; combined rates are always
driver-weighted; low-confidence series are visually distinct.
""")

if runs.empty or (runs["status"] == "complete").sum() == 0:
    st.info("No completed run yet. Start on the **Data** page, then launch a "
            "run from **Configure & Run**.")
