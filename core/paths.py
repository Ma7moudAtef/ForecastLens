"""The ONE place that resolves a filesystem path.

Every other module asks this module. Nothing else may build a path by hand —
`tests/unit/test_path_discipline.py` enforces that with an AST scan.

The rule that makes an exe behave like the web app:

    resource_path()  read-only, bundled WITH the code   (sys._MEIPASS)
    data_dir()       read-write, belongs to the USER    (%LOCALAPPDATA%)
    output_dir()     read-write, exports

`sys._MEIPASS` is read-only at runtime — on Windows it sits under Program
Files or a temp extraction directory. Writing the SQLite database, logs,
caches or exports beside the bundled code is the single most common reason
an app that works in development dies as a double-clicked exe.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

#: user-visible application folder name
APP_DIR_NAME = "ForecastLens"
#: folders earlier versions used — adopted if they already hold a user's data,
#: so anyone who ran a build carrying the other name keeps their working copy
LEGACY_DIR_NAMES = ("ForecastEngine",)
#: explicit override, honoured first (used by tests and locked-down machines).
#: The first name is the current one; the rest stay accepted so an existing
#: shortcut or scheduled task does not break.
DATA_DIR_ENVS = ("FORECASTLENS_DATA_DIR", "FORECASTENGINE_DATA_DIR")

#: where the default workbook lives, bundled vs in a source checkout
_SAMPLE_CANDIDATES = (
    Path("data") / "sample_public.xlsx",              # bundled by the spec
    Path("tests") / "fixtures" / "sample_public.xlsx",  # source checkout
)


def is_frozen() -> bool:
    """True inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def bundle_root() -> Path:
    """Directory the read-only application files live in.

    Frozen: PyInstaller's extraction/one-dir root. Source: the repo root.
    Never write here.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[1]


def resource_path(rel: str | os.PathLike[str]) -> Path:
    """Absolute path to a read-only asset shipped with the application."""
    return bundle_root() / Path(rel)


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _platform_data_dirs(app_name: str) -> list[Path]:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        roots = [Path(base)] if base else []
        roots.append(Path.home() / "AppData" / "Local")
        return [r / app_name for r in roots]
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / app_name]
    xdg = os.environ.get("XDG_DATA_HOME")
    out = [Path(xdg) / app_name] if xdg else []
    out.append(Path.home() / ".local" / "share" / app_name)
    out.append(Path.home() / f".{app_name.lower()}")
    return out


def data_dir() -> Path:
    """User-writable application directory. ALWAYS writable, never bundled.

    Order: explicit env override → a directory that ALREADY holds the user's
    data (this name first, then a name an earlier version used) → the
    preferred platform location → a temp directory as a last resort on
    locked-down machines.

    Existing beats preferred, deliberately. Picking the highest-priority
    location when a lower-priority one is already full of the user's work
    hands them an empty app and no explanation.
    """
    for env in DATA_DIR_ENVS:
        override = os.environ.get(env)
        if override:
            path = Path(override)
            path.mkdir(parents=True, exist_ok=True)
            return path

    candidates = _platform_data_dirs(APP_DIR_NAME)
    for candidate in candidates:
        if candidate.exists() and _writable(candidate):
            return candidate
    # only once this name has no home anywhere: adopt a previous version's
    # folder rather than starting the user over
    for legacy_name in LEGACY_DIR_NAMES:
        for legacy in _platform_data_dirs(legacy_name):
            if legacy.exists() and _writable(legacy):
                return legacy

    for candidate in candidates:
        if _writable(candidate):
            return candidate

    fallback = Path(tempfile.gettempdir()) / APP_DIR_NAME
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def output_dir() -> Path:
    """Where exports are written."""
    path = data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    """The SQLite result store. Under data_dir(), never beside the code."""
    override = os.environ.get("FORECASTLENS_DB")
    if override:
        return Path(override)
    return data_dir() / "forecastlens.db"


def working_workbook() -> Path:
    """The user's editable copy of the input data."""
    return data_dir() / "working_input.xlsx"


def bundled_sample() -> Path | None:
    """The default workbook shipped with the application, if present."""
    for rel in _SAMPLE_CANDIDATES:
        candidate = resource_path(rel)
        if candidate.exists():
            return candidate
    return None


def schema_sql() -> Path:
    """The SQLite schema — a bundled read-only asset."""
    return resource_path(Path("core") / "store" / "schema.sql")


def describe() -> dict[str, str]:
    """Everything the self-check and the UI footer need to report."""
    return {
        "frozen": str(is_frozen()),
        "bundle_root": str(bundle_root()),
        "data_dir": str(data_dir()),
        "output_dir": str(output_dir()),
        "database": str(db_path()),
    }
