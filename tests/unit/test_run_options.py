"""Lookback-window sweep and the on-disk analysis cache."""
import pickle
import time

import pandas as pd
import pytest

from core.config import MAX_WINDOWS, EngineConfig, window_sweep


# --- window sweep -------------------------------------------------------------

def test_small_range_is_used_whole():
    assert window_sweep(3, 6) == [3, 4, 5, 6]
    assert window_sweep(3, 3) == [3]


def test_wide_range_is_sampled_not_exhausted():
    windows = window_sweep(2, 60)
    assert len(windows) <= MAX_WINDOWS
    assert windows[0] == 2 and windows[-1] == 60      # ends always included
    assert windows == sorted(set(windows))


def test_order_of_arguments_does_not_matter():
    assert window_sweep(12, 3) == window_sweep(3, 12)


def test_windows_are_never_below_two():
    """A moving average needs at least two periods."""
    assert min(window_sweep(1, 5)) >= 2
    assert window_sweep(1, 1) == [2]


def test_sweep_feeds_a_valid_engine_config():
    cfg = EngineConfig(models={"lookback_windows": window_sweep(4, 20)})
    assert cfg.models.lookback_windows == sorted(set(cfg.models.lookback_windows))
    assert all(w >= 2 for w in cfg.models.lookback_windows)


# --- on-disk analysis cache ---------------------------------------------------

@pytest.fixture
def cache(tmp_path, monkeypatch):
    from app.components import datacache, paths

    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    datacache.clear()
    return datacache


def _workbook(tmp_path, rows=3) -> "pathlib.Path":
    import pathlib

    path = tmp_path / "wb.xlsx"
    bom = pd.DataFrame([{"item_code": "A1", "item_description": "w",
                         "uom": "p", "unit_price_$": 1.0, "unit_wt_kg": 0.1,
                         "category_level1": "c", "category_level2": "c",
                         "category_level3": "c"}])
    cons = pd.DataFrame([{
        "date": f"2024-{m:02d}-01", "item_code": "A1",
        "cons_qty_base_uom": float(m), "cons_qty_ton": 0.001, "cons_$": 1.0,
        "output_type": "x", "production_line": "a", "cons_rate": None,
        "cons_rate_uom": None} for m in range(1, rows + 1)])
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        bom.to_excel(w, sheet_name="bom", index=False)
        cons.to_excel(w, sheet_name="consumption", index=False)
    return path


def test_second_read_comes_from_the_cache(cache, tmp_path):
    path = _workbook(tmp_path)
    key = cache.fingerprint(path, EngineConfig(), {})
    calls = []

    def compute():
        calls.append(1)
        return {"answer": 42}

    first, from_cache = cache.get_or_compute(key, compute)
    assert first == {"answer": 42} and not from_cache
    second, from_cache = cache.get_or_compute(key, compute)
    assert second == {"answer": 42} and from_cache
    assert len(calls) == 1


def test_cache_survives_a_restart(cache, tmp_path):
    """The whole point: a new process must not redo the work."""
    path = _workbook(tmp_path)
    key = cache.fingerprint(path, EngineConfig(), {})
    cache.store(key, {"answer": 7})

    # simulate a fresh process: nothing in memory, only the file on disk
    assert cache.load(key) == {"answer": 7}


def test_editing_the_file_invalidates_the_cache(cache, tmp_path):
    path = _workbook(tmp_path, rows=3)
    key_before = cache.fingerprint(path, EngineConfig(), {})
    time.sleep(0.01)
    _workbook(tmp_path, rows=5)          # same path, new content
    key_after = cache.fingerprint(path, EngineConfig(), {})
    assert key_before != key_after


def test_changing_analysis_settings_invalidates_the_cache(cache, tmp_path):
    path = _workbook(tmp_path)
    base = cache.fingerprint(path, EngineConfig(), {})
    assert base != cache.fingerprint(
        path, EngineConfig(gate={"min_history_competition": 8}), {})
    assert base != cache.fingerprint(
        path, EngineConfig(granularity="weekly"), {})
    assert base != cache.fingerprint(
        path, EngineConfig(driver={"floor_fraction": 0.5}), {})


def test_declaring_a_mode_invalidates_the_cache(cache, tmp_path):
    """A planner declaration changes the answer, so a stale summary would
    describe a dataset the next run would not produce."""
    path = _workbook(tmp_path)
    base = cache.fingerprint(path, EngineConfig(), {})
    declared = cache.fingerprint(path, EngineConfig(), {"A1": "relative"})
    assert base != declared


def test_corrupt_entry_is_ignored_not_fatal(cache, tmp_path):
    path = _workbook(tmp_path)
    key = cache.fingerprint(path, EngineConfig(), {})
    cache.store(key, {"answer": 1})
    entry = cache.cache_dir() / f"analysis_{key}.pkl"
    entry.write_bytes(b"not a pickle")

    value, from_cache = cache.get_or_compute(key, lambda: {"answer": 2})
    assert value == {"answer": 2} and not from_cache


def test_cache_is_pruned_to_a_bounded_number_of_entries(cache, tmp_path):
    for i in range(cache.MAX_ENTRIES + 4):
        cache.store(f"key{i:03d}", {"i": i})
        time.sleep(0.002)
    entries = list(cache.cache_dir().glob("analysis_*.pkl"))
    assert len(entries) <= cache.MAX_ENTRIES


def test_clear_removes_everything(cache):
    cache.store("k1", {"a": 1})
    cache.store("k2", {"a": 2})
    assert cache.clear() >= 2
    assert cache.load("k1") is None
