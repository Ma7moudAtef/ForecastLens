"""Headless batch entry point.

    python -m cli.run --input tests/fixtures/sample_public.xlsx --db results.db
"""
from __future__ import annotations

import argparse
import json
import sys

from core.config import EngineConfig
from core.log import configure, get_logger
from core.pipeline import run_forecast

log = get_logger("cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ForecastLens batch runner")
    parser.add_argument("--input", required=True, help="Excel workbook path")
    parser.add_argument("--db", default="forecastlens.db", help="SQLite output path")
    parser.add_argument("--config", help="JSON file with EngineConfig overrides")
    parser.add_argument("--name", help="run name")
    parser.add_argument("--horizon", type=int, help="forecast horizon override")
    parser.add_argument("--jobs", type=int, help="parallel workers override")
    parser.add_argument("--items", help="comma-separated item codes to "
                                        "forecast (default: every item)")
    parser.add_argument("--derive-rates", action="store_true",
                        help="for items with no cons_rate but with driver "
                             "data, derive rate = consumption / driver")
    args = parser.parse_args(argv)

    configure()
    if args.config:
        with open(args.config, encoding="utf-8") as fh:
            cfg = EngineConfig.model_validate(json.load(fh))
    else:
        cfg = EngineConfig()
    if args.horizon:
        cfg.forecast.horizon = args.horizon
    if args.jobs:
        cfg.n_jobs = args.jobs
    if args.items:
        cfg.scope.item_codes = [c.strip() for c in args.items.split(",")
                                if c.strip()]
    if args.derive_rates:
        cfg.rate.derive_missing = True

    def progress(stage: str, fraction: float) -> None:
        log.info("[%3.0f%%] %s", fraction * 100, stage)

    run_id = run_forecast(args.input, cfg, db_path=args.db,
                          progress_cb=progress, run_name=args.name,
                          log_cb=log.info)
    print(run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
