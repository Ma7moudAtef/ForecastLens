"""Build identity: which commit produced this build, and when.

CI writes `core/_build_info.py` (gitignored) just before PyInstaller runs, so
a frozen exe carries its provenance. From a source checkout there is no such
file and the values fall back to git, then to "dev". The footer shows the
same string in both, so a bug report always names the build it came from.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"
UNKNOWN = "unknown"


def _from_build_info() -> tuple[str, str] | None:
    try:
        from core import _build_info  # type: ignore[attr-defined]
    except Exception:
        return None
    sha = getattr(_build_info, "BUILD_SHA", "") or ""
    built = getattr(_build_info, "BUILD_TIME", "") or ""
    return (sha, built) if sha or built else None


def _from_env() -> tuple[str, str] | None:
    sha = os.environ.get("FORECASTLENS_BUILD_SHA") or os.environ.get("GITHUB_SHA")
    built = os.environ.get("FORECASTLENS_BUILD_TIME")
    if not sha and not built:
        return None
    return (sha or UNKNOWN, built or UNKNOWN)


def _from_git() -> tuple[str, str] | None:
    try:
        root = Path(__file__).resolve().parents[1]
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short=7", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        when = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%cI"],
            capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        return (sha, when) if sha else None
    except Exception:
        return None


def build_sha() -> str:
    for source in (_from_build_info, _from_env, _from_git):
        found = source()
        if found and found[0]:
            return found[0][:12]
    return "dev"


def build_time() -> str:
    for source in (_from_build_info, _from_env, _from_git):
        found = source()
        if found and found[1]:
            return found[1]
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_stamp() -> str:
    """One line for the UI footer and the console banner."""
    from core.paths import is_frozen

    kind = "exe" if is_frozen() else "source"
    return f"ForecastEngine {VERSION} · {kind} · build {build_sha()} · {build_time()}"


def write_build_info(target: Path, sha: str, built: str | None = None) -> Path:
    """Used by the build workflow to stamp a bundle."""
    built = built or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    target.write_text(
        '"""Generated at build time. Do not edit, do not commit."""\n'
        f'BUILD_SHA = "{sha}"\n'
        f'BUILD_TIME = "{built}"\n',
        encoding="utf-8")
    return target
