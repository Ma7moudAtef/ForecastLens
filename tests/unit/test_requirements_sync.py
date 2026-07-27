"""requirements.txt is what Streamlit Community Cloud installs (it takes
precedence over pyproject.toml there). It must stay in sync with the runtime
dependencies in pyproject.toml, and must never contain packaging/dev tools —
the cloud deploy failed once because poetry tried to resolve pyinstaller."""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_IN_REQUIREMENTS = {"pyinstaller", "pytest", "pytest-cov", "pre-commit"}


def _name(spec: str) -> str:
    return re.split(r"[><=!~\[;]", spec, 1)[0].strip().lower()


def _requirements() -> dict[str, str]:
    out = {}
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out[_name(line)] = line
    return out


def _pyproject_runtime() -> dict[str, str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return {_name(d): d for d in data["project"]["dependencies"]}


def test_requirements_matches_pyproject_runtime_deps():
    assert _requirements() == _pyproject_runtime()


def test_no_build_or_dev_tools_in_requirements():
    assert not (set(_requirements()) & FORBIDDEN_IN_REQUIREMENTS)


def test_pyinstaller_extra_is_python_bounded():
    """Every PyInstaller release caps its supported Python; an unbounded
    requirement makes poetry's full-range resolution unsolvable (the exact
    Community Cloud failure). The extra must carry a python_version marker."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package_extra = data["project"]["optional-dependencies"]["package"]
    pyinstaller = [d for d in package_extra if _name(d) == "pyinstaller"]
    assert pyinstaller, "pyinstaller extra missing"
    assert "python_version" in pyinstaller[0]
