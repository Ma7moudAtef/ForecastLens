"""Cached read access for the UI. Pages read completed results only —
computation happens in core.pipeline, never inside a Streamlit rerun."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from core.store.repository import Repository

DB_ENV = "FORECASTLENS_DB"


def db_path() -> Path:
    return Path(os.environ.get(DB_ENV, "forecastlens.db"))


def _stamp() -> float:
    """Cache key component: the database file's mtime, so caches invalidate
    the moment a run finishes writing."""
    p = db_path()
    return p.stat().st_mtime if p.exists() else 0.0


def repo() -> Repository:
    r = Repository(db_path())
    r.init_schema()
    return r


@st.cache_data(show_spinner=False)
def load_runs(stamp: float) -> pd.DataFrame:
    return repo().list_runs()


@st.cache_data(show_spinner=False)
def load_series(stamp: float) -> pd.DataFrame:
    return repo().get_series()


@st.cache_data(show_spinner=False)
def load_observations(stamp: float) -> pd.DataFrame:
    return repo().get_observations()


@st.cache_data(show_spinner=False)
def load_selections(stamp: float, run_id: str) -> pd.DataFrame:
    return repo().get_selections(run_id)


@st.cache_data(show_spinner=False)
def load_forecasts(stamp: float, run_id: str) -> pd.DataFrame:
    return repo().get_forecasts(run_id)


@st.cache_data(show_spinner=False)
def load_warnings(stamp: float, run_id: str | None) -> pd.DataFrame:
    return repo().get_warnings(run_id)


@st.cache_data(show_spinner=False)
def load_validation(stamp: float, run_id: str, series_id: str) -> pd.DataFrame:
    return repo().get_validation_results(run_id, series_id)


@st.cache_data(show_spinner=False)
def load_driver(stamp: float) -> pd.DataFrame:
    return repo().get_driver()


@st.cache_data(show_spinner=False)
def load_standard_rates(stamp: float) -> pd.DataFrame:
    return repo().get_standard_rates()


@st.cache_data(show_spinner=False)
def load_items(stamp: float) -> pd.DataFrame:
    return repo().get_items()


@st.cache_data(show_spinner=False)
def load_accuracy(stamp: float) -> pd.DataFrame:
    return repo().get_accuracy()


def stamp() -> float:
    return _stamp()


def pick_run(st_container) -> str | None:
    """Run selector; defaults to the latest complete run."""
    runs = load_runs(stamp())
    complete = runs[runs["status"] == "complete"]
    if complete.empty:
        st_container.info("No completed runs yet — start one on the "
                          "Configure & Run page.")
        return None
    labels = {
        f"{r.name} · {r.created_at} · {r.run_id}": r.run_id
        for r in complete.itertuples()}
    choice = st_container.selectbox(
        "Run", list(labels), index=0,
        help="Which forecast batch to display. Every completed run is kept, "
             "so you can compare a new run against an earlier one.")
    return labels[choice]
