"""Scoped runs and user-facing run numbering.

A run may cover the whole catalogue, one item, or a chosen list. Scope
restricts what is FORECAST — never what is analyzed, so cold-start items
keep borrowing pooled behaviour from every category sibling.
"""
from pathlib import Path

import pandas as pd
import pytest

from core.config import EngineConfig, RunScope
from core.pipeline import run_forecast
from core.store.repository import Repository

pytestmark = pytest.mark.slow

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_public.xlsx"


def _items(n: int) -> list[str]:
    bom = pd.read_excel(FIXTURE, sheet_name="bom", engine="openpyxl")
    consumption = pd.read_excel(FIXTURE, sheet_name="consumption",
                                engine="openpyxl")
    usable = [c for c in bom["item_code"]
              if c in set(consumption["item_code"])]
    return usable[:n]


def test_scope_note_describes_the_selection():
    assert RunScope().note() == "all items"
    assert RunScope().covers_all()
    assert RunScope(item_codes=["a"]).note() == "1 item (a)"
    assert RunScope(item_codes=["a", "b"]).note() == "2 items"
    assert not RunScope(item_codes=["a"]).covers_all()


def test_single_item_run_forecasts_only_that_item(tmp_path):
    code = _items(1)[0]
    db = tmp_path / "r.db"
    cfg = EngineConfig(scope={"item_codes": [code]},
                       forecast={"horizon": 3})
    run_id = run_forecast(FIXTURE, cfg, db_path=db, run_name="scoped")

    with Repository(db) as repo:
        sel = repo.get_selections(run_id)
        fc = repo.get_forecasts(run_id)
        series = repo.get_series()
        runs = repo.list_runs()

    assert not sel.empty
    assert set(sel["series_id"].str.split("|").str[0]) == {code}
    assert set(fc["series_id"]) == set(sel["series_id"])
    # every series is still analyzed and stored — only forecasting is scoped
    assert len(series) == 820
    row = runs[runs["run_id"] == run_id].iloc[0]
    assert row["n_series"] == len(sel)
    assert row["scope_note"] == f"1 item ({code})"


def test_item_list_run_covers_exactly_those_items(tmp_path):
    codes = _items(3)
    db = tmp_path / "r.db"
    cfg = EngineConfig(scope={"item_codes": codes}, forecast={"horizon": 3})
    run_id = run_forecast(FIXTURE, cfg, db_path=db)

    with Repository(db) as repo:
        sel = repo.get_selections(run_id)
        runs = repo.list_runs()
    assert set(sel["series_id"].str.split("|").str[0]) == set(codes)
    assert runs.iloc[0]["scope_note"] == f"{len(codes)} items"


def test_scoped_run_is_much_faster_than_a_full_run(tmp_path):
    """The point of scoping: a planner iterating on one material should not
    wait for the whole catalogue."""
    import time

    code = _items(1)[0]
    db = tmp_path / "r.db"
    started = time.perf_counter()
    run_forecast(FIXTURE, EngineConfig(scope={"item_codes": [code]},
                                       forecast={"horizon": 3}),
                 db_path=db)
    assert time.perf_counter() - started < 60


def test_unknown_item_scope_fails_loudly(tmp_path):
    db = tmp_path / "r.db"
    cfg = EngineConfig(scope={"item_codes": ["no-such-item"]})
    with pytest.raises(RuntimeError, match="no forecastable series"):
        run_forecast(FIXTURE, cfg, db_path=db)


def test_runs_are_numbered_for_the_user(tmp_path):
    code = _items(1)[0]
    db = tmp_path / "r.db"
    cfg = EngineConfig(scope={"item_codes": [code]}, forecast={"horizon": 3})
    first = run_forecast(FIXTURE, cfg, db_path=db)
    second = run_forecast(FIXTURE, cfg, db_path=db, run_name="my label")

    with Repository(db) as repo:
        runs = repo.list_runs()
    numbers = dict(zip(runs["run_id"], runs["run_number"]))
    assert numbers[first] == 1
    assert numbers[second] == 2
    # newest first
    assert list(runs["run_id"])[0] == second

    from app.components.db import run_label
    labels = [run_label(r) for r in runs.itertuples()]
    assert labels[0].startswith("Run 2 — my label")
    assert labels[1].startswith("Run 1")
    for label, rid in zip(labels, runs["run_id"]):
        assert rid not in label          # identifier never shown


def test_run_number_backfills_on_an_older_database(tmp_path):
    """A database created before run numbering existed must migrate, not
    crash, and must keep numbering from where it left off."""
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE run (
            run_id TEXT PRIMARY KEY, name TEXT, created_at TEXT NOT NULL,
            input_hash TEXT, source_name TEXT, config_json TEXT NOT NULL,
            status TEXT NOT NULL, n_series INTEGER, duration_s REAL);
        INSERT INTO run VALUES ('old1', 'legacy', '2026-01-01T00:00:00',
                                '', '', '{}', 'complete', 5, 1.0);
    """)
    conn.commit()
    conn.close()

    with Repository(db) as repo:
        runs = repo.list_runs()
        assert runs.iloc[0]["run_number"] == 1
        new_id = repo.create_run("{}", scope_note="all items")
        runs = repo.list_runs()
    assert dict(zip(runs["run_id"], runs["run_number"]))[new_id] == 2
