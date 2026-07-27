"""Packaged-exe entry point.

`multiprocessing.freeze_support()` MUST be the first statement executed, or
the frozen Windows exe fork-bombs: every joblib worker re-runs this script
from the top.

Launches Streamlit programmatically via `streamlit.web.bootstrap` — the
`streamlit` console binary does not exist inside a PyInstaller bundle.
Writes only beside the exe or to %LOCALAPPDATA%; no registry, no admin.
"""
import multiprocessing

multiprocessing.freeze_support()

import os  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402


def _bundle_root() -> Path:
    # one-dir mode: sys._MEIPASS points at the directory with bundled data
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def _data_dir() -> Path:
    """User-writable location for the SQLite result store."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ForecastLens"
    else:
        base = Path.home() / ".forecastlens"
    base.mkdir(parents=True, exist_ok=True)
    return base


def main() -> None:
    root = _bundle_root()
    script = root / "app" / "main.py"

    os.environ.setdefault("FORECASTLENS_DB", str(_data_dir() / "forecastlens.db"))
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")

    from streamlit.web import bootstrap

    flag_options = {
        "server.headless": True,
        "browser.gatherUsageStats": False,
        "global.developmentMode": False,
    }
    bootstrap.load_config_options(flag_options=flag_options)
    bootstrap.run(str(script), False, [], flag_options)


if __name__ == "__main__":
    main()
