"""On-disk cache for the Data page's read-and-validate step.

`st.cache_data` only lives as long as the process, so every restart re-read
and re-validated the whole workbook — around two minutes on the default data
before the page showed anything. This cache survives restarts: the result is
pickled beside the app's other data, keyed by the file's identity AND by
everything that changes the answer.

The key deliberately includes the analysis-relevant configuration and the
planner's mode declarations: if a stale result were served after one of those
changed, the Data page would describe a dataset that no longer matches what a
run would produce.
"""
from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path
from typing import Any, Callable

from app.components import paths
from core.config import EngineConfig
from core.log import get_logger

log = get_logger("app.datacache")

#: bump when the cached payload's shape or the analysis itself changes, so
#: old entries are ignored rather than deserialized into the wrong structure
CACHE_VERSION = 3
MAX_ENTRIES = 8


def cache_dir() -> Path:
    """core.paths owns the location; this is only a named re-export."""
    return paths.cache_dir()


def fingerprint(path: Path, cfg: EngineConfig,
                mode_overrides: dict[str, str] | None = None) -> str:
    """Identity of a cached analysis: the file, the settings that shape it,
    and the planner declarations applied to it."""
    stat = path.stat()
    payload = {
        "version": CACHE_VERSION,
        "path": str(path.resolve()),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "granularity": cfg.granularity.value,
        "min_history": cfg.gate.min_history_competition,
        "seasonal_min": cfg.gate.seasonal_min_history,
        "driver_floor": cfg.driver.floor_fraction,
        "mode_overrides": sorted((mode_overrides or {}).items()),
    }
    blob = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:20]


def _entry(key: str) -> Path:
    return cache_dir() / f"analysis_{key}.pkl"


def _prune() -> None:
    entries = sorted(cache_dir().glob("analysis_*.pkl"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in entries[MAX_ENTRIES:]:
        stale.unlink(missing_ok=True)


def load(key: str) -> Any | None:
    entry = _entry(key)
    if not entry.exists():
        return None
    try:
        with entry.open("rb") as fh:
            return pickle.load(fh)
    except Exception as exc:            # corrupt or written by another build
        log.warning("ignoring unreadable cache entry %s: %s", entry.name, exc)
        entry.unlink(missing_ok=True)
        return None


def store(key: str, value: Any) -> None:
    entry = _entry(key)
    tmp = entry.with_suffix(".tmp")
    try:
        with tmp.open("wb") as fh:
            pickle.dump(value, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(entry)              # atomic: never leave a half-file
        _prune()
    except Exception as exc:            # a cache failure must never break the app
        log.warning("could not write cache entry %s: %s", entry.name, exc)
        tmp.unlink(missing_ok=True)


def get_or_compute(key: str, compute: Callable[[], Any]) -> tuple[Any, bool]:
    """Return (value, from_cache). Any cache problem falls back to computing."""
    cached = load(key)
    if cached is not None:
        return cached, True
    value = compute()
    store(key, value)
    return value, False


def clear() -> int:
    """Drop every cached analysis. Returns how many entries were removed."""
    entries = list(cache_dir().glob("analysis_*.pkl"))
    for entry in entries:
        entry.unlink(missing_ok=True)
    return len(entries)
