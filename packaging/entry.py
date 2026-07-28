"""Packaged-application entry point.

`multiprocessing.freeze_support()` MUST be the first statement executed, or
the frozen Windows exe fork-bombs: every joblib worker re-runs this script
from the top.

Subcommands exist so the frozen binary can do everything the source version
can — which is what makes exe/web parity testable rather than assumed:

    (no arguments)      launch the Streamlit UI
    --selfcheck         run the startup checks and exit
    --version           print the build stamp and exit
    --run-forecast      headless pipeline run, same core.pipeline as the web
    --export            write an Excel export of a run
"""
import multiprocessing

multiprocessing.freeze_support()

import os  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402


def _prepare_path() -> None:
    """A frozen bundle already has the modules; a source checkout needs the
    repo root on sys.path so `core` and `app` import the same way."""
    root = Path(__file__).resolve().parents[1]
    if not getattr(sys, "frozen", False) and str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _launch_ui() -> int:
    from core import paths
    from core.selfcheck import report
    from core.version import build_stamp

    ok, text = report()
    print(text, flush=True)
    if not ok:
        print("\nThe application will not start. Fix the items above, then "
              "run it again.", flush=True)
        return 2

    script = paths.resource_path(Path("app") / "main.py")
    os.environ.setdefault("FORECASTLENS_DB", str(paths.db_path()))
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")
    print(f"\n{build_stamp()}\nOpening http://localhost:8501 …", flush=True)

    from streamlit.web import bootstrap

    flag_options = {
        "server.headless": True,
        "browser.gatherUsageStats": False,
        "global.developmentMode": False,
    }
    bootstrap.load_config_options(flag_options=flag_options)
    bootstrap.run(str(script), False, [], flag_options)
    return 0


def _run_forecast(argv: list[str]) -> int:
    """Headless run — the same core.pipeline the UI calls."""
    import argparse

    from core.config import EngineConfig
    from core.log import configure, get_logger
    from core.paths import db_path
    from core.pipeline import run_forecast

    parser = argparse.ArgumentParser(prog="ForecastEngine --run-forecast")
    parser.add_argument("--run-forecast", action="store_true")
    parser.add_argument("--input", required=True)
    parser.add_argument("--db", default=None)
    parser.add_argument("--horizon", type=int, default=None)
    parser.add_argument("--items", default=None)
    parser.add_argument("--derive-rates", action="store_true")
    parser.add_argument("--jobs", type=int, default=None)
    parser.add_argument("--name", default=None)
    args = parser.parse_args(argv)

    configure()
    log = get_logger("exe")
    cfg = EngineConfig()
    if args.horizon:
        cfg.forecast.horizon = args.horizon
    if args.items:
        cfg.scope.item_codes = [c.strip() for c in args.items.split(",") if c.strip()]
    if args.derive_rates:
        cfg.rate.derive_missing = True
    if args.jobs:
        cfg.n_jobs = args.jobs

    target = Path(args.db) if args.db else db_path()
    run_id = run_forecast(args.input, cfg, db_path=target,
                          progress_cb=lambda s, f: log.info("[%3.0f%%] %s",
                                                            f * 100, s),
                          log_cb=log.info, run_name=args.name)
    print(run_id)
    return 0


def _export(argv: list[str]) -> int:
    import argparse

    from core.export import export_workbook
    from core.paths import db_path, output_dir

    parser = argparse.ArgumentParser(prog="ForecastEngine --export")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--db", default=None)
    parser.add_argument("--run", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    target = Path(args.db) if args.db else db_path()
    out = Path(args.out) if args.out else output_dir() / "forecastengine_export.xlsx"
    written = export_workbook(target, args.run, out)
    print(written)
    return 0


def main(argv: list[str] | None = None) -> int:
    _prepare_path()
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--version" in argv:
        from core.version import build_stamp
        print(build_stamp())
        return 0
    if "--selfcheck" in argv:
        from core.selfcheck import report
        ok, text = report()
        print(text)
        return 0 if ok else 2
    if "--run-forecast" in argv:
        return _run_forecast(argv)
    if "--export" in argv:
        return _export(argv)
    return _launch_ui()


if __name__ == "__main__":
    sys.exit(main())
