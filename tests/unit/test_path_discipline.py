"""One path resolver, used everywhere.

The divergence between a working web app and a broken exe is almost always a
path: something written next to the (read-only) bundle, or an asset located
from `__file__`, or a relative path that depends on the working directory.
These tests keep `core.paths` the only module allowed to make those choices.
"""
import ast
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESOLVER = ROOT / "core" / "paths.py"

#: application code (tests and packaging specs are allowed more latitude)
SOURCES = sorted(
    p for p in list((ROOT / "core").rglob("*.py"))
    + list((ROOT / "app").rglob("*.py"))
    + list((ROOT / "cli").rglob("*.py"))
    if "__pycache__" not in p.parts)

#: the sys.path bootstrap at the top of each Streamlit script legitimately
#: uses __file__ — it runs before `core` is importable
BOOTSTRAP_MARKER = "path bootstrap"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_only_the_resolver_knows_about_frozen_bundles():
    """_MEIPASS / sys.frozen appear in exactly one module, plus the launcher
    that must set them up before `core` is importable."""
    allowed = {RESOLVER, ROOT / "packaging" / "entry.py"}
    offenders = []
    for path in SOURCES:
        if path in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if "_MEIPASS" in text:
            offenders.append(f"{path.relative_to(ROOT)}: _MEIPASS")
        if "sys.frozen" in text or 'getattr(sys, "frozen"' in text:
            offenders.append(f"{path.relative_to(ROOT)}: sys.frozen")
    assert not offenders, (
        "frozen-bundle detection must live in core.paths only: " +
        ", ".join(offenders))


def test_no_module_hardcodes_a_writable_file_location():
    """Databases, logs, caches and exports come from core.paths, so they land
    in a user-writable folder rather than inside the bundle."""
    banned = (".db", ".sqlite", ".sqlite3", ".log")
    offenders = []
    for path in SOURCES:
        if path == RESOLVER:
            continue
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if value.endswith(banned) and "/" not in value.replace("\\", "/"):
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} {value!r}")
    assert not offenders, (
        "bare writable filenames resolve against the working directory; ask "
        "core.paths instead: " + ", ".join(offenders))


def test_assets_are_not_located_from_dunder_file():
    """`__file__` points inside the bundle when frozen and a module may not
    even exist on disk — assets must go through resource_path()."""
    offenders = []
    for path in SOURCES:
        if path == RESOLVER:
            continue
        text = path.read_text(encoding="utf-8")
        if "__file__" not in text:
            continue
        if BOOTSTRAP_MARKER in text and text.count("__file__") == 1:
            continue          # the documented sys.path bootstrap
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Name) or node.id != "__file__":
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    # core/version.py locates the git checkout, which only exists in source
    offenders = [o for o in offenders if not o.startswith("core/version.py")]
    assert not offenders, (
        "use core.paths.resource_path() to find bundled assets: " +
        ", ".join(offenders))


def test_no_module_assumes_the_working_directory():
    offenders = []
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        for marker in ("os.getcwd(", "Path.cwd(", "os.chdir("):
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)}: {marker}")
    assert not offenders, (
        "the working directory differs when frozen or double-clicked: " +
        ", ".join(offenders))


# --- the resolver's own behaviour --------------------------------------------

def test_resource_path_follows_the_bundle(monkeypatch, tmp_path):
    from core import paths

    assert paths.resource_path("x").parent == paths.bundle_root()
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.bundle_root() == tmp_path
    assert paths.resource_path("app/main.py") == tmp_path / "app" / "main.py"
    assert paths.is_frozen()


def test_data_dir_is_never_inside_the_bundle(monkeypatch, tmp_path):
    """The rule that keeps a frozen build alive."""
    from core import paths

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(bundle), raising=False)
    for env in paths.DATA_DIR_ENVS:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    for resolved in (paths.data_dir(), paths.output_dir(), paths.db_path().parent,
                     paths.cache_dir(), paths.log_dir()):
        assert bundle not in resolved.resolve().parents, \
            f"{resolved} is inside the read-only bundle"


def test_data_dir_honours_an_explicit_override(monkeypatch, tmp_path):
    from core import paths

    monkeypatch.setenv("FORECASTLENS_DATA_DIR", str(tmp_path / "chosen"))
    assert paths.data_dir() == tmp_path / "chosen"
    assert paths.data_dir().exists()


def _posix_home(monkeypatch, tmp_path):
    from core import paths

    for env in paths.DATA_DIR_ENVS:
        monkeypatch.delenv(env, raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(paths.os, "name", "posix")
    monkeypatch.setattr(paths.sys, "platform", "linux")
    return home


def test_data_dir_adopts_a_previous_versions_folder(monkeypatch, tmp_path):
    """Renaming the app must not strand a user's working copy and database."""
    from core import paths

    home = _posix_home(monkeypatch, tmp_path)
    legacy_name = paths.LEGACY_DIR_NAMES[0]
    legacy = home / ".local" / "share" / legacy_name
    legacy.mkdir(parents=True)
    (legacy / "forecastlens.db").write_text("old data", encoding="utf-8")
    assert paths.data_dir() == legacy


def test_an_existing_folder_beats_the_preferred_one(monkeypatch, tmp_path):
    """A user whose data sits in a lower-priority location must keep it.
    Choosing the preferred path instead hands them an empty app and no
    explanation — which is exactly what a rename would otherwise cause."""
    from core import paths

    home = _posix_home(monkeypatch, tmp_path)
    preferred, *_rest = paths._platform_data_dirs(paths.APP_DIR_NAME)
    lower = home / f".{paths.APP_DIR_NAME.lower()}"
    lower.mkdir(parents=True)
    (lower / "forecastlens.db").write_text("real data", encoding="utf-8")

    assert not preferred.exists()
    assert paths.data_dir() == lower


def test_the_preferred_location_is_used_on_a_clean_machine(monkeypatch, tmp_path):
    from core import paths

    _posix_home(monkeypatch, tmp_path)
    preferred, *_rest = paths._platform_data_dirs(paths.APP_DIR_NAME)
    assert paths.data_dir() == preferred


def test_data_dir_falls_back_when_the_home_location_is_unwritable(
        monkeypatch, tmp_path):
    from core import paths

    for env in paths.DATA_DIR_ENVS:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(paths, "_writable", lambda p: False)
    monkeypatch.setattr(paths, "_platform_data_dirs",
                        lambda name: [tmp_path / "denied" / name])
    resolved = paths.data_dir()
    assert resolved.exists() and os.access(resolved, os.W_OK)


def test_db_path_lives_under_the_data_dir(monkeypatch, tmp_path):
    from core import paths

    monkeypatch.setenv("FORECASTLENS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("FORECASTLENS_DB", raising=False)
    assert paths.db_path().parent == tmp_path


def test_config_default_db_is_resolved_not_relative(monkeypatch, tmp_path):
    from core import paths
    from core.config import AppConfig

    monkeypatch.setenv("FORECASTLENS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("FORECASTLENS_DB", raising=False)
    assert AppConfig().db_path.is_absolute()
    assert AppConfig().db_path.parent == paths.data_dir()


def test_schema_and_sample_resolve(monkeypatch):
    from core import paths

    assert paths.schema_sql().exists()
    assert paths.bundled_sample() is not None
    assert paths.bundled_sample().exists()
