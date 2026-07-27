"""Headless actuals import: compare a stored run's forecasts with what
actually happened, record the error, and flag drifting series.

    python -m cli.import_actuals --input newer_data.xlsx --db results.db

The Accuracy tab was removed from the UI; this is how accuracy history is
maintained. It feeds the Portfolio page's "confidence declining" badge.
"""
from __future__ import annotations

import argparse
import sys

from core.config import EngineConfig
from core.learn.accuracy import import_actuals
from core.log import configure, get_logger
from core.store.repository import Repository

log = get_logger("cli.actuals")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import actuals and update forecast accuracy history")
    parser.add_argument("--input", required=True,
                        help="workbook containing newer consumption history")
    parser.add_argument("--db", default="forecastlens.db",
                        help="SQLite results database")
    parser.add_argument("--run", help="run id to compare against "
                                      "(default: the latest complete run)")
    args = parser.parse_args(argv)

    configure()
    run_id = args.run
    if not run_id:
        with Repository(args.db) as repo:
            run_id = repo.latest_complete_run_id()
        if not run_id:
            print("no completed run to compare against", file=sys.stderr)
            return 1

    result = import_actuals(args.input, args.db, run_id, EngineConfig())
    log.info("matched %d forecast period(s) across %d series; %d drifting",
             result.n_matched, result.n_series, result.n_drift)
    for sid in result.drifting_series:
        log.info("drift: %s", sid)
    print(f"{result.n_matched} matched, {result.n_series} series, "
          f"{result.n_drift} flagged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
