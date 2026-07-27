"""Optional shared-secret gate for hosted deployment.

Local-first by default: when the environment variable is unset, no gate.
When set, every page requires the secret once per session. HTTPS is the
host's responsibility.
"""
from __future__ import annotations

import hmac
import os

import streamlit as st

from core.config import AppConfig


def require_secret() -> None:
    secret = os.environ.get(AppConfig().shared_secret_env_var, "")
    if not secret:
        return
    if st.session_state.get("_authed"):
        return
    st.title("🔒 ForecastLens")
    entered = st.text_input("Access key", type="password")
    if entered:
        if hmac.compare_digest(entered, secret):
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("Wrong key.")
    st.stop()
