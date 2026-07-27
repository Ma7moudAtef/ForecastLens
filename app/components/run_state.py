"""Background run management.

Streamlit re-runs its whole script on every widget interaction — a full run
(~10^5 model fits) cannot live inside that cycle. The batch executes on a
plain thread calling core.pipeline.run_forecast(); the page polls a shared
state dict. This works identically inside the packaged exe (no subprocess,
no python on PATH needed).
"""
from __future__ import annotations

import threading
import traceback

_state: dict = {"running": False, "stage": "", "fraction": 0.0,
                "run_id": None, "error": None}
_lock = threading.Lock()


def state() -> dict:
    with _lock:
        return dict(_state)


def _progress(stage: str, fraction: float) -> None:
    with _lock:
        _state["stage"] = stage
        _state["fraction"] = fraction


def start_run(input_path: str, cfg, db_path: str, run_name: str | None) -> bool:
    """Launch a batch run; returns False if one is already in flight."""
    with _lock:
        if _state["running"]:
            return False
        _state.update({"running": True, "stage": "starting", "fraction": 0.0,
                       "run_id": None, "error": None})

    def worker() -> None:
        from core.pipeline import run_forecast
        try:
            run_id = run_forecast(input_path, cfg, db_path=db_path,
                                  progress_cb=_progress, run_name=run_name)
            with _lock:
                _state.update({"running": False, "run_id": run_id,
                               "fraction": 1.0, "stage": "done"})
        except Exception as exc:
            with _lock:
                _state.update({"running": False,
                               "error": f"{exc}\n{traceback.format_exc()}"})

    threading.Thread(target=worker, daemon=True, name="forecast-run").start()
    return True
