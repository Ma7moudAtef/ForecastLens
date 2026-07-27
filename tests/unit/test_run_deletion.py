"""Deleting run history: one run, or all of it.

Planner decisions (model overrides, mode declarations) and the loaded
reference data are NOT run history and must survive.
"""
import pandas as pd

from core.store.repository import Repository


def _seed(repo: Repository, run_id: str) -> None:
    repo.write_selections(pd.DataFrame([{
        "run_id": run_id, "series_id": "a|L|X", "model_name": "SES",
        "window": None, "mase": 0.5, "confidence": 0.8,
        "confidence_label": "high", "route": "compete",
        "reason_code": "competition_winner", "reason_text": "because",
        "rejected_json": "[]", "is_override": 0, "override_reason": None}]))
    repo.write_forecasts(pd.DataFrame([{
        "run_id": run_id, "series_id": "a|L|X", "period": "2026-07",
        "target_value": 1.0, "lower_80": 0.5, "upper_80": 1.5,
        "lower_95": 0.1, "upper_95": 2.0, "driver_plan": None,
        "reconstructed_demand": 31.0, "demand_lower_80": 15.0,
        "demand_upper_80": 46.0, "demand_lower_95": 3.0,
        "demand_upper_95": 62.0, "confidence": 0.8}]))
    repo.write_validation_results(pd.DataFrame([{
        "run_id": run_id, "series_id": "a|L|X", "model_name": "SES",
        "window": None, "mase": 0.5, "mae": 1.0, "rmse": 1.0, "mape": 1.0,
        "smape": 1.0, "n_origins": 4, "fit_seconds": 0.1, "status": "ok",
        "fail_reason": None}]))
    repo.write_warnings(run_id, pd.DataFrame([{
        "series_id": "a|L|X", "code": "X", "severity": "info", "count": 1,
        "message": "m"}]))


def test_delete_run_removes_everything_it_produced(tmp_path):
    with Repository(tmp_path / "r.db") as repo:
        keep = repo.create_run("{}", scope_note="all items")
        drop = repo.create_run("{}", scope_note="1 item (a)")
        _seed(repo, keep)
        _seed(repo, drop)

        repo.delete_run(drop)

        assert set(repo.list_runs()["run_id"]) == {keep}
        assert repo.get_selections(drop).empty
        assert repo.get_forecasts(drop).empty
        assert repo.get_validation_results(drop).empty
        assert (repo.get_warnings()["run_id"] == drop).sum() == 0
        # the surviving run is untouched
        assert len(repo.get_selections(keep)) == 1
        assert len(repo.get_forecasts(keep)) == 1


def test_delete_run_keeps_planner_decisions(tmp_path):
    with Repository(tmp_path / "r.db") as repo:
        run_id = repo.create_run("{}")
        _seed(repo, run_id)
        repo.set_model_override("a|L|X", "Theta", "planner knows better")
        repo.set_mode_override("a", "absolute", "not driver-dependent")

        repo.delete_run(run_id)

        assert len(repo.get_model_overrides()) == 1
        assert len(repo.get_mode_overrides()) == 1


def test_delete_all_runs_clears_history_and_restarts_numbering(tmp_path):
    with Repository(tmp_path / "r.db") as repo:
        for _ in range(3):
            _seed(repo, repo.create_run("{}"))
        assert len(repo.list_runs()) == 3

        removed = repo.delete_all_runs()
        assert removed == 3
        assert repo.list_runs().empty
        assert repo.get_warnings().empty
        assert repo.latest_complete_run_id() is None

        fresh = repo.create_run("{}", scope_note="all items")
        runs = repo.list_runs()
        assert runs.iloc[0]["run_number"] == 1
        assert runs.iloc[0]["run_id"] == fresh


def test_numbering_does_not_shift_when_a_middle_run_is_deleted(tmp_path):
    """Users refer to 'Run 2' — deleting Run 1 must not renumber Run 3."""
    with Repository(tmp_path / "r.db") as repo:
        first = repo.create_run("{}")
        second = repo.create_run("{}")
        third = repo.create_run("{}")
        repo.delete_run(first)

        numbers = dict(zip(repo.list_runs()["run_id"],
                           repo.list_runs()["run_number"]))
        assert numbers == {second: 2, third: 3}
        # and a new run continues after the highest number, never reusing one
        assert dict(zip(repo.list_runs()["run_id"],
                        repo.list_runs()["run_number"]))[third] == 3
        fresh = repo.create_run("{}")
        assert dict(zip(repo.list_runs()["run_id"],
                        repo.list_runs()["run_number"]))[fresh] == 4


def test_delete_is_safe_on_an_unknown_run(tmp_path):
    with Repository(tmp_path / "r.db") as repo:
        repo.delete_run("no-such-run")          # must not raise
        assert repo.list_runs().empty
        assert repo.delete_all_runs() == 0


def test_legacy_database_backfills_scope_note(tmp_path):
    """Old rows get a truthful scope note — scoping did not exist then, so
    those runs did cover every item. This also removes the NULL that broke
    the run picker."""
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE run (
            run_id TEXT PRIMARY KEY, name TEXT, created_at TEXT NOT NULL,
            input_hash TEXT, source_name TEXT, config_json TEXT NOT NULL,
            status TEXT NOT NULL, n_series INTEGER, duration_s REAL);
        INSERT INTO run VALUES ('old1', NULL, '2026-01-01T00:00:00',
                                '', '', '{}', 'complete', 820, 160.0);
    """)
    conn.commit()
    conn.close()

    with Repository(db) as repo:
        row = repo.list_runs().iloc[0]
    assert row["scope_note"] == "all items"
    assert row["run_number"] == 1

    from app.components.db import run_label
    with Repository(db) as repo:
        labels = [run_label(r) for r in repo.list_runs().itertuples()]
    assert labels[0].startswith("Run 1")
