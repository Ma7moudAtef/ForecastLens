"""Background run management.

Streamlit re-runs its whole script on every widget interaction — a full run
(~10^5 model fits) cannot live inside that cycle. The batch executes on a
plain thread calling core.pipeline.run_forecast(); the page polls this
shared state. This works identically inside the packaged exe (no subprocess,
no python on PATH needed).

The thread also collects a verbose log and honours an abort request, which
the pipeline polls between stages and between series chunks.
"""
from __future__ import annotations

import threading
import time
import traceback

MAX_LOG_LINES = 2000

_state: dict = {
    "running": False,
    "stage": "",
    "fraction": 0.0,
    "run_id": None,
    "error": None,
    "cancel_requested": False,
    "cancelled": False,
    "log": [],
    "started_at": None,
    "finished_at": None,
}
_lock = threading.Lock()


def state() -> dict:
    with _lock:
        snapshot = dict(_state)
        snapshot["log"] = list(_state["log"])
        return snapshot


def log_lines() -> list[str]:
    with _lock:
        return list(_state["log"])


def elapsed() -> float:
    with _lock:
        if not _state["started_at"]:
            return 0.0
        end = _state["finished_at"] or time.time()
        return end - _state["started_at"]


def _append(message: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    with _lock:
        _state["log"].append(f"{stamp}  {message}")
        if len(_state["log"]) > MAX_LOG_LINES:
            del _state["log"][:-MAX_LOG_LINES]


def _progress(stage: str, fraction: float) -> None:
    with _lock:
        _state["stage"] = stage
        _state["fraction"] = fraction


def _should_cancel() -> bool:
    with _lock:
        return _state["cancel_requested"]


def request_cancel() -> None:
    """Ask the running batch to stop. The pipeline checks between stages and
    between series chunks, so a stop takes effect within seconds rather than
    killing workers mid-fit."""
    with _lock:
        if _state["running"]:
            _state["cancel_requested"] = True
    _append("Abort requested — stopping after the current chunk…")


def start_run(input_path: str, cfg, db_path: str, run_name: str | None) -> bool:
    """Launch a batch run; returns False if one is already in flight."""
    with _lock:
        if _state["running"]:
            return False
        _state.update({
            "running": True, "stage": "starting", "fraction": 0.0,
            "run_id": None, "error": None, "cancel_requested": False,
            "cancelled": False, "log": [], "started_at": time.time(),
            "finished_at": None,
        })
    _append(f"Starting run on {input_path}")

    def worker() -> None:
        from core.pipeline import RunCancelled, run_forecast
        try:
            run_id = run_forecast(input_path, cfg, db_path=db_path,
                                  progress_cb=_progress, run_name=run_name,
                                  log_cb=_append, cancel_cb=_should_cancel)
            with _lock:
                _state.update({"running": False, "run_id": run_id,
                               "fraction": 1.0, "stage": "done",
                               "finished_at": time.time()})
        except RunCancelled:
            _append("Run cancelled. No partial results were saved.")
            with _lock:
                _state.update({"running": False, "cancelled": True,
                               "stage": "cancelled",
                               "finished_at": time.time()})
        except Exception as exc:
            _append(f"Run FAILED: {exc}")
            with _lock:
                _state.update({"running": False,
                               "stage": "failed",
                               "finished_at": time.time(),
                               "error": f"{exc}\n{traceback.format_exc()}"})

    threading.Thread(target=worker, daemon=True, name="forecast-run").start()
    return True
