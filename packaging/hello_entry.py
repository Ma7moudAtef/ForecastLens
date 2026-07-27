"""Entry point for the hello-world packaging spike exe."""
import multiprocessing

multiprocessing.freeze_support()

import os  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402


def main() -> None:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    script = root / "hello_app.py"

    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

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
