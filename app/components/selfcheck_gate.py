"""Run the startup checks inside the UI too.

The packaged launcher prints them to its console, but `streamlit run` and
hosted deployments have no console the user reads — so the same checks run
here and, on failure, replace the app with a plain explanation instead of
letting a page fail deeper in with a traceback.
"""
from __future__ import annotations

import streamlit as st

from core.selfcheck import run_checks


@st.cache_data(show_spinner=False, ttl=300)
def _results() -> list[tuple[str, bool, str, str]]:
    return [(r.name, r.ok, r.detail, r.remedy) for r in run_checks()]


def enforce() -> None:
    failures = [r for r in _results() if not r[1]]
    if not failures:
        return
    st.error("ForecastEngine cannot start — the checks below failed.")
    for name, _ok, detail, remedy in failures:
        st.markdown(f"**{name}** — {detail}")
        if remedy:
            st.caption(f"→ {remedy}")
    st.stop()
