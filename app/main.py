"""ForecastLens entrypoint — the navigation router.

All computation happens in core.pipeline; every view only reads completed
results from SQLite. Page files live in app/views/ and are wired here via
st.navigation so each tab carries a real name (Overview, Data, …).
"""
# --- path bootstrap ----------------------------------------------------------
# Make the repo root importable no matter how this script is launched:
# `streamlit run`, Streamlit Community Cloud, the frozen exe, or tests.
# `streamlit run app/main.py` puts app/ on sys.path, NOT the project root, so
# `from app...` / `from core...` fail without this (ModuleNotFoundError).
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# -----------------------------------------------------------------------------
import streamlit as st

from app.components import auth

st.set_page_config(page_title="ForecastLens", page_icon="📈", layout="wide")
auth.require_secret()

nav = st.navigation([
    st.Page("views/overview.py", title="Overview", icon="🏠", default=True),
    st.Page("views/data.py", title="Data", icon="🗂️"),
    st.Page("views/configure_run.py", title="Configure & Run", icon="⚙️"),
    st.Page("views/explorer.py", title="Explorer", icon="🔍"),
    st.Page("views/portfolio.py", title="Portfolio & Export", icon="📋"),
])
nav.run()
