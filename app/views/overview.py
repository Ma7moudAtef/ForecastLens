"""Overview — what the app is, current state, and how the models think."""
# --- path bootstrap ----------------------------------------------------------
# Make the repo root importable no matter how this script is launched:
# `streamlit run`, Streamlit Community Cloud, the frozen exe, or tests.
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# -----------------------------------------------------------------------------
import streamlit as st

from app.components import db, paths, samples

st.title("🏠 Overview")
st.caption("Adaptive consumption forecasting with plain-language reasoning")

runs = db.load_runs(db.stamp())
series = db.load_series(db.stamp())

col1, col2, col3, col4 = st.columns(4)
col1.metric("Completed runs", int((runs["status"] == "complete").sum())
            if not runs.empty else 0,
            help="Forecast batches that finished successfully. Every run is "
                 "kept and can be reopened on any page.")
col2.metric("Series", len(series),
            help="Atomic forecasting units: one per (item, line, output "
                 "type) combination found in the data.")
if not series.empty:
    col3.metric("Relative / Absolute",
                f"{(series['mode'] == 'relative').sum()} / "
                f"{(series['mode'] == 'absolute').sum()}",
                help="Relative items depend on a production driver (their "
                     "rate is forecast); Absolute items are independent "
                     "(their quantity is forecast directly).")
    col4.metric("Orphan series", int(series["is_orphan"].sum()),
                help="Series with a consumption rate but no driver record "
                     "at all — they need planner resolution on the Data "
                     "page.")

st.markdown("""
**Workflow**

1. **🗂️ Data** — the default workbook is already loaded. Review validation,
   edit tables in place, or bring your own file.
2. **⚙️ Configure & Run** — set the horizon and model options, launch a run.
3. **🔍 Explorer** — inspect any item (picked by description): chart,
   intelligence card, model competition, plain-language reasoning, override.
4. **📋 Portfolio** — triage: which items actually need attention.
5. **🎯 Accuracy** — import newer actuals, track forecast error over time.
6. **📤 Export** — Excel/CSV of forecasts, selections and warnings.
""")

if runs.empty or (runs["status"] == "complete").sum() == 0:
    st.info("No completed run yet — the default data is preloaded, so you "
            "can go straight to **Configure & Run** and press Run.")

# --- sample download ----------------------------------------------------------
st.subheader("Sample data",
             help="A small extract of the default workbook so you can see "
                  "the expected format before preparing your own file.")
sample_path = paths.bundled_sample()
if sample_path:
    st.download_button(
        "⬇️ Download sample workbook (first 10 rows + data dictionary)",
        samples.build_sample_workbook(sample_path),
        file_name="forecastlens_sample.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="First 10 rows of every sheet plus a data_dictionary sheet "
             "explaining each column and what the engine does with it.")

# --- model explainer ----------------------------------------------------------
st.subheader("The forecasting models — what runs under the hood",
             help="Every forecast comes from a competition (or routing) "
                  "between these models. Expand any family to see what it "
                  "does, and when and why the engine uses it.")
st.caption("You never pick a model yourself unless you want to: the engine "
           "back-tests every allowed candidate on each item's own history "
           "and explains its choice. This is the cast it chooses from.")

with st.expander("📏 Baselines — Naive, Seasonal Naive, Drift, Mean"):
    st.markdown("""
These exist to be beaten; when nothing beats them, they ARE the honest answer.

- **Naive** repeats the last actual value. Used when history is very short or
  the series is a random walk with no learnable pattern.
- **Seasonal Naive** repeats the same period from the previous cycle (next
  March = last March). Used when a stable repeating pattern exists and there
  are at least two full cycles of history.
- **Drift** extends the straight line from first to last observation. Used for
  steady long-run climbs or declines.
- **Mean** forecasts the average of all history, flat forward. In Relative
  mode it is **driver-weighted** — periods when the line barely ran do not
  distort the average. Wins on genuinely stable consumption rates.
""")

with st.expander("🪟 Averaging windows — Moving Average, Weighted Moving Average"):
    st.markdown("""
- **Moving Average** averages only the last k periods, dropping the distant
  past. Used when the series is stable but old history is no longer
  representative (a process change, a new supplier…).
- **Weighted Moving Average** additionally counts recent periods more.
- Both are **driver-weighted** in Relative mode: each period's rate counts in
  proportion to how much the driver actually ran, so the result equals total
  consumption ÷ total driver over the window — the arithmetically correct
  combined rate.
""")

with st.expander("📉 Exponential smoothing — SES, Holt, Damped Holt, "
                 "Holt-Winters, ETS (the workhorses)"):
    st.markdown("""
Every past observation counts, but its influence fades the further back it
is; the models *learn* how fast to forget from the data itself.

- **SES** (simple exponential smoothing): level only — the go-to for stable
  series with no direction.
- **Holt** adds a trend, so the forecast slopes. Used for sustained climbs.
- **Damped Holt** ⭐ is Holt with the trend flattening as the horizon
  extends — because trends rarely last. One of the most reliable performers
  in forecasting practice.
- **Holt-Winters** adds seasonality on top (fixed-amount or percentage
  swings). The key model for strongly seasonal businesses. Needs at least
  two full cycles of history.
- **ETS** tries the valid combinations of trend and seasonality
  automatically and keeps the best-fitting form.
""")

with st.expander("📐 Statistical — Theta, ARIMA (optional)"):
    st.markdown("""
- **Theta** ⭐ splits the series into a heavily-smoothed long-run line and an
  exaggerated short-run line, forecasts both and averages. Won the M3
  forecasting competition; extremely hard to beat on short monthly business
  series — exactly this data's shape.
- **ARIMA** models the series through its own past values and errors. Off by
  default: on short histories it is unstable and hard to explain, and rarely
  beats ETS or Theta. Enable it on Configure & Run for series with ≥ 24
  periods if you want it in the competition.
""")

with st.expander("🕳️ Intermittent demand — Croston, SBA, TSB"):
    st.markdown("""
For items that move sporadically (many zero periods), normal error metrics
break down — so these series are **routed** here by their demand pattern,
not competed. The idea: track how *big* demand is when it happens and how
*often* it happens, separately.

- **Croston** — the original method. Kept for reference and overrides; it
  carries a known upward bias.
- **SBA** ⭐ — Croston with the bias mathematically corrected. The default
  for sporadic items.
- **TSB** ⭐ — tracks the *probability* of demand every period, so the
  forecast **decays toward zero** during long silences. This is the model
  that recognizes items going obsolete — essential for pharma, FMCG and
  long-tail retail.
""")

with st.expander("⚓ Domain anchors — Standard Rate, Category Prior"):
    st.markdown("""
Not time-series models: they inject knowledge the history does not contain,
and they carry the items whose history is too short to model.

- **Standard-Rate Anchor** uses your engineered standard consumption rate as
  the forecast. When it beats every fitted model, that is a credible,
  important message — and actual-vs-standard is a KPI in itself.
- **Category Prior** lets a new or thin item inherit the pooled behaviour of
  its category siblings (most specific category first). This is what gives
  brand-new materials a defensible starting forecast.
""")

with st.expander("🤝 Ensemble — the average of the best few"):
    st.markdown("""
When several models validate almost equally well (within ~10% of each
other), their **average** is often more accurate and more stable than any
single member — individual errors cancel. The engine only offers the
ensemble in exactly that situation.
""")

with st.expander("🧭 How the engine decides which models compete"):
    st.markdown("""
| Situation | What happens |
|---|---|
| Fewer than 6 usable periods | No competition — cold-start ladder: standard rate (Relative) → category prior → naive. Confidence is capped at *low*. |
| Sporadic/lumpy demand pattern | Routed to the intermittent family (SBA default, TSB when the series has gone quiet). |
| 6–23 usable periods | Non-seasonal candidates compete under rolling back-testing. |
| 24+ usable periods | Full set including the seasonal models (and ARIMA if enabled). |

Candidates are ranked on scale-free validation error (MASE); near-ties go to
the more stable, then the **simpler** model. Every choice — and every
rejection — is explained in plain language on the Explorer page.
""")
