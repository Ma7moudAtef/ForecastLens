"""Startup self-check.

A double-clicked exe that dies silently is close to undiagnosable for a
non-technical user. Before the UI appears we verify the handful of things
that actually break in a frozen build, and report each failure in a sentence
that names what is wrong and what to do — never a raw traceback.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from core import paths


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    remedy: str = ""

    def line(self) -> str:
        mark = "OK  " if self.ok else "FAIL"
        text = f"[{mark}] {self.name}: {self.detail}"
        if not self.ok and self.remedy:
            text += f"\n       → {self.remedy}"
        return text


def _check_data_dir() -> CheckResult:
    # Resolve first and remember it: building the failure message must never
    # call the thing that just failed, or the check crashes instead of
    # reporting — the exact silent death this check exists to prevent.
    directory: Path | None = None
    try:
        directory = paths.data_dir()
        probe = directory / ".startup-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return CheckResult("Data folder", True, f"writable at {directory}")
    except Exception as exc:
        where = str(directory) if directory is not None else \
            "the user data folder (could not even be resolved)"
        return CheckResult(
            "Data folder", False,
            f"cannot write to {where} ({type(exc).__name__}: {exc})",
            "Set FORECASTLENS_DATA_DIR to a folder you can write to, or "
            "run the app from a location your account owns.")


def _check_database() -> CheckResult:
    target = paths.db_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target)
        conn.execute("CREATE TABLE IF NOT EXISTS _startup_probe (x INTEGER)")
        conn.execute("DROP TABLE _startup_probe")
        conn.commit()
        conn.close()
        return CheckResult("Results database", True, f"ready at {target}")
    except Exception as exc:
        return CheckResult(
            "Results database", False,
            f"cannot open {target} ({type(exc).__name__}: {exc})",
            "The database lives in your user folder. If it is locked, close "
            "any other copy of the app; if it is corrupt, rename it and the "
            "app will create a fresh one.")


def _check_assets() -> CheckResult:
    missing: list[str] = []
    schema = paths.schema_sql()
    if not schema.exists():
        missing.append(str(schema))
    sample = paths.bundled_sample()
    if sample is None:
        missing.append("sample workbook (data/sample_public.xlsx)")
    app_entry = paths.resource_path(Path("app") / "main.py")
    if not app_entry.exists():
        missing.append(str(app_entry))
    if missing:
        return CheckResult(
            "Bundled files", False,
            "missing from this build: " + ", ".join(missing),
            "The download is incomplete or was partially quarantined. "
            "Re-extract the zip in full, then allow the folder in your "
            "antivirus and try again.")
    return CheckResult("Bundled files", True,
                       f"all present under {paths.bundle_root()}")


#: import name → what the user loses if it is missing
REQUIRED_IMPORTS = {
    "pandas": "reading and shaping your data",
    "numpy": "the numeric engine",
    "scipy.stats": "statistics and prediction intervals",
    "scipy.optimize": "splitting consumption into fixed and variable parts",
    "statsmodels.tsa.holtwinters": "the smoothing forecast models",
    "statsmodels.tsa.arima.model": "the ARIMA model",
    "statsmodels.tsa.seasonal": "seasonality analysis",
    "statsmodels.tsa.stattools": "stationarity testing",
    "joblib": "running forecasts in parallel",
    "openpyxl": "reading and writing Excel files",
    "plotly": "the charts",
    "pydantic": "configuration validation",
    "streamlit": "the user interface",
}


def _check_imports() -> CheckResult:
    import importlib

    broken: list[str] = []
    for module, purpose in REQUIRED_IMPORTS.items():
        try:
            importlib.import_module(module)
        except Exception as exc:
            broken.append(f"{module} ({purpose}) — {type(exc).__name__}: {exc}")
    if broken:
        return CheckResult(
            "Dependencies", False, "; ".join(broken),
            "This build is incomplete. Re-download it; if the problem "
            "persists the packaging step dropped a module and the build "
            "needs regenerating.")
    return CheckResult("Dependencies", True,
                       f"all {len(REQUIRED_IMPORTS)} imports resolved")


CHECKS = (_check_data_dir, _check_database, _check_assets, _check_imports)


def run_checks() -> list[CheckResult]:
    results = []
    for check in CHECKS:
        try:
            results.append(check())
        except Exception as exc:      # a check must never crash the launcher
            results.append(CheckResult(
                check.__name__, False, f"check itself failed: {exc}",
                "Please report this message."))
    return results


def report(results: list[CheckResult] | None = None) -> tuple[bool, str]:
    """(everything_ok, printable report)."""
    from core.version import build_stamp

    results = run_checks() if results is None else results
    ok = all(r.ok for r in results)
    lines = [build_stamp(), "-" * 72]
    lines += [r.line() for r in results]
    lines.append("-" * 72)
    lines.append("Startup checks passed — opening the app…" if ok else
                 "STARTUP FAILED. The app cannot run until the items marked "
                 "FAIL above are resolved.")
    return ok, "\n".join(lines)
