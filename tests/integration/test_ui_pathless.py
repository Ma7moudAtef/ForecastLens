"""Regression: every page must render when the project is NOT pip-installed
and the working directory is NOT the repo root — exactly how `streamlit run
app/main.py` behaves on a fresh clone and on Streamlit Community Cloud.

The subprocess strips the repo root from sys.path before loading each page;
without the per-page bootstrap this reproduces the original
`ModuleNotFoundError: No module named 'app'` verbatim.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
PAGES = [APP / "main.py", *sorted((APP / "pages").glob("[0-9]*.py"))]


def test_pages_render_without_install_and_from_foreign_cwd(tmp_path):
    code = textwrap.dedent(f"""
        import sys
        root = {str(ROOT)!r}
        sys.path = [p for p in sys.path if p not in ("", ".", root)]
        from streamlit.testing.v1 import AppTest
        failures = []
        for page in {[str(p) for p in PAGES]!r}:
            at = AppTest.from_file(page, default_timeout=120)
            at.run()
            if at.exception:
                failures.append((page, at.exception[0].message))
        if failures:
            raise SystemExit("pages failed without repo on sys.path: "
                             + repr(failures))
        print("OK", len({[str(p) for p in PAGES]!r}))
    """)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,                       # foreign cwd, like a user's shell
        capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
