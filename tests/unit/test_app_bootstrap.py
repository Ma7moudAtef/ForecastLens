"""Every app script must bootstrap sys.path before importing app/core.

`streamlit run app/main.py` puts app/ on sys.path — NOT the project root —
so without the bootstrap every page dies with ModuleNotFoundError unless the
project happens to be pip-installed. This static guard catches a new page
added without the bootstrap; the runtime proof is in
tests/integration/test_ui_pathless.py.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"

PAGES = [APP / "main.py", *sorted([p for p in (APP / "views").glob("*.py") if not p.name.startswith("__")])]


def _first_project_import_line(tree: ast.Module) -> int | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module \
                and node.module.split(".")[0] in ("app", "core"):
            return node.lineno
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] in ("app", "core") for a in node.names):
                return node.lineno
    return None


def test_every_page_bootstraps_sys_path_before_project_imports():
    assert PAGES, "no app pages found"
    for page in PAGES:
        src = page.read_text(encoding="utf-8")
        assert "sys.path.insert" in src, f"{page.name}: missing path bootstrap"
        tree = ast.parse(src)
        import_line = _first_project_import_line(tree)
        assert import_line is not None, f"{page.name}: no project imports?"
        bootstrap_line = src[:src.index("sys.path.insert")].count("\n") + 1
        assert bootstrap_line < import_line, (
            f"{page.name}: bootstrap must run before app/core imports")


def test_bootstrap_resolves_to_repo_root():
    """parents[N] must point at the repo root from each file's location."""
    for page in PAGES:
        depth = len(page.relative_to(ROOT).parts) - 1
        src = page.read_text(encoding="utf-8")
        assert f"parents[{depth}]" in src, (
            f"{page.name}: bootstrap depth must be parents[{depth}]")
