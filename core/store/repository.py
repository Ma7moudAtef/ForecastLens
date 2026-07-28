"""All database access. Parameterized queries only — no string-built SQL.

The repository is the single boundary between the engine and SQLite. The UI
reads through it (via pandas), the pipeline writes through it.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

def _schema_path() -> Path:
    """Resolved through core.paths so the frozen build finds the bundled
    copy rather than a path next to a module that no longer exists on disk."""
    from core.paths import schema_sql

    return schema_sql()


def series_id_of(item_code: str, line: str | None, output_type: str | None) -> str:
    """Deterministic, human-readable series identity — comparable across runs."""
    return f"{item_code}|{line or ''}|{output_type or ''}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repository:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    # --- lifecycle -----------------------------------------------------------
    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def init_schema(self) -> None:
        self.conn.executescript(_schema_path().read_text(encoding="utf-8"))
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created.
        CREATE TABLE IF NOT EXISTS never alters an existing table."""
        existing = {row[1] for row in
                    self.conn.execute("PRAGMA table_info(run)")}
        for column, ddl in (("run_number", "INTEGER"), ("scope_note", "TEXT")):
            if column not in existing:
                self.conn.execute(f"ALTER TABLE run ADD COLUMN {column} {ddl}")
        # backfill numbers for runs created before this column existed
        missing = self.conn.execute(
            "SELECT run_id FROM run WHERE run_number IS NULL"
            " ORDER BY created_at").fetchall()
        if missing:
            start = self.conn.execute(
                "SELECT COALESCE(MAX(run_number), 0) FROM run").fetchone()[0]
            for offset, (run_id,) in enumerate(missing, start=1):
                self.conn.execute(
                    "UPDATE run SET run_number=? WHERE run_id=?",
                    (start + offset, run_id))
        # runs predating the scope feature necessarily covered every item
        self.conn.execute(
            "UPDATE run SET scope_note='all items'"
            " WHERE scope_note IS NULL OR scope_note=''")

        obs_cols = {row[1] for row in
                    self.conn.execute("PRAGMA table_info(observation)")}
        if obs_cols and "is_applicable" not in obs_cols:
            self.conn.execute("ALTER TABLE observation ADD COLUMN "
                              "is_applicable INTEGER NOT NULL DEFAULT 1")
        series_cols = {row[1] for row in
                       self.conn.execute("PRAGMA table_info(series)")}
        if series_cols and "n_applicable" not in series_cols:
            self.conn.execute("ALTER TABLE series ADD COLUMN "
                              "n_applicable INTEGER")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Repository":
        self.init_schema()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- runs ----------------------------------------------------------------
    def create_run(self, config_json: str, source_name: str = "",
                   input_hash: str = "", name: str | None = None,
                   scope_note: str = "") -> str:
        run_id = uuid.uuid4().hex[:12]
        run_number = self.conn.execute(
            "SELECT COALESCE(MAX(run_number), 0) + 1 FROM run").fetchone()[0]
        self.conn.execute(
            "INSERT INTO run (run_id, run_number, name, created_at, input_hash,"
            " source_name, config_json, status, scope_note)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, run_number, name or "", _now(), input_hash,
             source_name, config_json, "running", scope_note))
        self.conn.commit()
        return run_id

    def finish_run(self, run_id: str, status: str, n_series: int,
                   duration_s: float) -> None:
        self.conn.execute(
            "UPDATE run SET status=?, n_series=?, duration_s=? WHERE run_id=?",
            (status, n_series, duration_s, run_id))
        self.conn.commit()

    def list_runs(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT run_id, run_number, name, created_at, source_name, status,"
            " n_series, duration_s, scope_note FROM run"
            " ORDER BY run_number DESC", self.conn)

    def get_run_config(self, run_id: str) -> dict:
        row = self.conn.execute(
            "SELECT config_json FROM run WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    #: every table that carries per-run results
    _RUN_TABLES = ("validation_result", "selection", "forecast", "warning",
                   "accuracy_history")

    def delete_run(self, run_id: str) -> None:
        """Remove one run and everything it produced. Planner decisions
        (model and mode overrides) and the loaded reference data are kept —
        they are not run history."""
        with self.conn:
            for table in self._RUN_TABLES:
                self.conn.execute(f"DELETE FROM {table} WHERE run_id=?",
                                  (run_id,))
            self.conn.execute("DELETE FROM run WHERE run_id=?", (run_id,))

    def delete_all_runs(self) -> int:
        """Clear the whole run history. Returns how many runs were removed.
        Overrides and reference data survive; run numbering restarts at 1."""
        with self.conn:
            n = self.conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
            for table in self._RUN_TABLES:
                self.conn.execute(f"DELETE FROM {table}")
            self.conn.execute("DELETE FROM run")
        return int(n)

    def latest_complete_run_id(self) -> str | None:
        row = self.conn.execute(
            "SELECT run_id FROM run WHERE status='complete'"
            " ORDER BY created_at DESC LIMIT 1").fetchone()
        return row[0] if row else None

    # --- bulk writers --------------------------------------------------------
    def replace_reference_data(self, items: pd.DataFrame, driver: pd.DataFrame,
                               standard_rates: pd.DataFrame) -> None:
        """Items / driver / standard rates reflect the latest loaded workbook."""
        with self.conn:
            self.conn.execute("DELETE FROM item")
            self.conn.execute("DELETE FROM driver")
            self.conn.execute("DELETE FROM standard_rate")
            items.to_sql("item", self.conn, if_exists="append", index=False)
            if not driver.empty:
                driver.to_sql("driver", self.conn, if_exists="append", index=False)
            if not standard_rates.empty:
                standard_rates.to_sql("standard_rate", self.conn,
                                      if_exists="append", index=False)

    def replace_series(self, series: pd.DataFrame,
                       observations: pd.DataFrame) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM series")
            self.conn.execute("DELETE FROM observation")
            series.to_sql("series", self.conn, if_exists="append", index=False)
            observations.to_sql("observation", self.conn, if_exists="append",
                                index=False)

    def write_warnings(self, run_id: str | None, warnings: pd.DataFrame) -> None:
        if warnings.empty:
            return
        df = warnings.copy()
        df["run_id"] = run_id
        df.to_sql("warning", self.conn, if_exists="append", index=False)
        self.conn.commit()

    def clear_unattached_warnings(self) -> None:
        """Warnings with no run_id belong to the latest data load."""
        self.conn.execute("DELETE FROM warning WHERE run_id IS NULL")
        self.conn.commit()

    def write_validation_results(self, df: pd.DataFrame) -> None:
        if not df.empty:
            df.to_sql("validation_result", self.conn, if_exists="append", index=False)
            self.conn.commit()

    def write_selections(self, df: pd.DataFrame) -> None:
        if not df.empty:
            df.to_sql("selection", self.conn, if_exists="append", index=False)
            self.conn.commit()

    def write_forecasts(self, df: pd.DataFrame) -> None:
        if not df.empty:
            df.to_sql("forecast", self.conn, if_exists="append", index=False)
            self.conn.commit()

    # --- overrides -----------------------------------------------------------
    def set_model_override(self, series_id: str, model_name: str,
                           reason: str) -> None:
        self.conn.execute(
            "INSERT INTO model_override (series_id, model_name, reason, locked,"
            " created_at) VALUES (?,?,?,1,?) ON CONFLICT(series_id) DO UPDATE SET"
            " model_name=excluded.model_name, reason=excluded.reason, locked=1,"
            " created_at=excluded.created_at",
            (series_id, model_name, reason, _now()))
        self.conn.commit()

    def clear_model_override(self, series_id: str) -> None:
        self.conn.execute("DELETE FROM model_override WHERE series_id=?",
                          (series_id,))
        self.conn.commit()

    def get_model_overrides(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT series_id, model_name, reason, locked FROM model_override"
            " WHERE locked=1", self.conn)

    def set_mode_override(self, item_code: str, mode: str, reason: str) -> None:
        if mode not in ("relative", "absolute"):
            raise ValueError(f"invalid mode: {mode}")
        self.conn.execute(
            "INSERT INTO mode_override (item_code, mode, reason, created_at)"
            " VALUES (?,?,?,?) ON CONFLICT(item_code) DO UPDATE SET"
            " mode=excluded.mode, reason=excluded.reason,"
            " created_at=excluded.created_at",
            (item_code, mode, reason, _now()))
        self.conn.commit()

    def clear_mode_override(self, item_code: str) -> None:
        self.conn.execute("DELETE FROM mode_override WHERE item_code=?",
                          (item_code,))
        self.conn.commit()

    def get_mode_overrides(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT item_code, mode, reason FROM mode_override", self.conn)

    # --- read queries (UI) ---------------------------------------------------
    def get_series(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM series", self.conn)

    def get_observations(self, series_ids: list[str] | None = None) -> pd.DataFrame:
        if series_ids:
            ph = ",".join("?" * len(series_ids))
            return pd.read_sql_query(
                f"SELECT * FROM observation WHERE series_id IN ({ph})"
                " ORDER BY series_id, period", self.conn, params=series_ids)
        return pd.read_sql_query(
            "SELECT * FROM observation ORDER BY series_id, period", self.conn)

    def get_driver(self, driver_type: str | None = None) -> pd.DataFrame:
        if driver_type:
            return pd.read_sql_query(
                "SELECT * FROM driver WHERE driver_type=?", self.conn,
                params=(driver_type,))
        return pd.read_sql_query("SELECT * FROM driver", self.conn)

    def get_standard_rates(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM standard_rate", self.conn)

    def get_items(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM item", self.conn)

    def get_warnings(self, run_id: str | None = None) -> pd.DataFrame:
        if run_id:
            return pd.read_sql_query(
                "SELECT * FROM warning WHERE run_id=? OR run_id IS NULL",
                self.conn, params=(run_id,))
        return pd.read_sql_query("SELECT * FROM warning", self.conn)

    def get_selections(self, run_id: str) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM selection WHERE run_id=?", self.conn, params=(run_id,))

    def get_validation_results(self, run_id: str,
                               series_id: str | None = None) -> pd.DataFrame:
        if series_id:
            return pd.read_sql_query(
                "SELECT * FROM validation_result WHERE run_id=? AND series_id=?",
                self.conn, params=(run_id, series_id))
        return pd.read_sql_query(
            "SELECT * FROM validation_result WHERE run_id=?", self.conn,
            params=(run_id,))

    def get_forecasts(self, run_id: str,
                      series_ids: list[str] | None = None) -> pd.DataFrame:
        if series_ids:
            ph = ",".join("?" * len(series_ids))
            return pd.read_sql_query(
                f"SELECT * FROM forecast WHERE run_id=? AND series_id IN ({ph})"
                " ORDER BY series_id, period", self.conn,
                params=[run_id, *series_ids])
        return pd.read_sql_query(
            "SELECT * FROM forecast WHERE run_id=? ORDER BY series_id, period",
            self.conn, params=(run_id,))

    # --- accuracy ------------------------------------------------------------
    def write_accuracy(self, df: pd.DataFrame) -> None:
        if df.empty:
            return
        rows = df.to_dict("records")
        with self.conn:
            self.conn.executemany(
                "INSERT INTO accuracy_history (series_id, period, forecast_value,"
                " actual_value, error, abs_pct_error, model_name, run_id,"
                " recorded_at) VALUES (:series_id, :period, :forecast_value,"
                " :actual_value, :error, :abs_pct_error, :model_name, :run_id,"
                " :recorded_at) ON CONFLICT(series_id, period, run_id) DO UPDATE"
                " SET actual_value=excluded.actual_value, error=excluded.error,"
                " abs_pct_error=excluded.abs_pct_error,"
                " recorded_at=excluded.recorded_at", rows)

    def get_accuracy(self, series_id: str | None = None) -> pd.DataFrame:
        if series_id:
            return pd.read_sql_query(
                "SELECT * FROM accuracy_history WHERE series_id=?"
                " ORDER BY period", self.conn, params=(series_id,))
        return pd.read_sql_query(
            "SELECT * FROM accuracy_history ORDER BY series_id, period", self.conn)
