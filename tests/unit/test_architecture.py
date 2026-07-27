"""Architectural rule: no module under core/ may import streamlit.

This single constraint is what allows the same engine to run behind the UI,
in a CLI batch job, inside the packaged exe, and behind a future API.
"""
import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[2] / "core"
FORBIDDEN = {"streamlit"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_never_imports_streamlit():
    offenders = []
    for py in sorted(CORE.rglob("*.py")):
        bad = _imported_roots(py) & FORBIDDEN
        if bad:
            offenders.append((str(py.relative_to(CORE.parent)), sorted(bad)))
    assert not offenders, f"core/ modules import forbidden packages: {offenders}"


def test_core_has_modules():
    assert any(CORE.rglob("*.py")), "core/ package missing"
