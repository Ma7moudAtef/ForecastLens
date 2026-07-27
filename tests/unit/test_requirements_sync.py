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


#: The oldest Streamlit the app actually runs on.
#: - 1.36 introduced st.navigation / st.Page (the named tabs)
#: - 1.49 let st.dataframe / st.data_editor take width="stretch"
#: - 1.51 let st.plotly_chart take width="stretch"  <- the binding constraint
#: Verified by inspecting the published wheels; below 1.51 every chart in
#: app/components/ui.py raises TypeError at render time.
MIN_STREAMLIT = (1, 51)


def _floor(spec: str) -> tuple[int, ...]:
    match = re.search(r">=\s*([0-9.]+)", spec)
    assert match, f"no lower bound in {spec!r}"
    return tuple(int(p) for p in match.group(1).split("."))


def test_streamlit_floor_supports_every_api_the_app_uses():
    for source in (_requirements(), _pyproject_runtime()):
        assert _floor(source["streamlit"]) >= MIN_STREAMLIT, (
            f"streamlit floor {source['streamlit']} is below the "
            f"{'.'.join(map(str, MIN_STREAMLIT))} the UI needs")


def test_installed_streamlit_meets_the_declared_floor():
    """CI and developers must run at least what we ship against."""
    import streamlit

    installed = tuple(int(p) for p in streamlit.__version__.split(".")[:2])
    assert installed >= _floor(_requirements()["streamlit"])


def test_charts_accept_stretch_width_on_the_installed_version():
    """The API that sets the floor — proven present, not assumed."""
    import inspect

    import streamlit as st

    for fn in (st.plotly_chart, st.dataframe, st.data_editor):
        params = inspect.signature(fn).parameters
        assert "width" in params, fn.__name__
        annotation = str(params["width"].annotation)
        assert "Width" in annotation or "stretch" in annotation, \
            f"{fn.__name__}: {annotation}"


def test_pyinstaller_extra_is_python_bounded():
    """Every PyInstaller release caps its supported Python; an unbounded
    requirement makes poetry's full-range resolution unsolvable (the exact
    Community Cloud failure). The extra must carry a python_version marker."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package_extra = data["project"]["optional-dependencies"]["package"]
    pyinstaller = [d for d in package_extra if _name(d) == "pyinstaller"]
    assert pyinstaller, "pyinstaller extra missing"
    assert "python_version" in pyinstaller[0]
