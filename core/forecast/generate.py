"""Point forecasts, prediction intervals, confidence.

All forecasts are clipped at zero — consumption is never negative, and
several smoothing models predict below zero on noisy data. The confidence
score combines residual-based accuracy WITH data sufficiency: a 3-period
series can produce a deceptively tight interval, and without the sufficiency
penalty planners would trust the weakest forecasts most.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import EngineConfig
from core.models.base import BaseModel
from core.prep.calendar import full_range


def confidence_score(mase: float | None, n_reliable: int, forecastability: float,
                     data_quality: float, cfg: EngineConfig,
                     validation_skipped: bool) -> float:
    """0..1. Sufficiency (history depth), forecastability and data quality
    penalize residual-only optimism. Cold-start / routed selections without
    validation are capped at 'low'."""
    accuracy = 1.0 / (1.0 + mase) if mase is not None and np.isfinite(mase) else 0.40
    sufficiency = min(1.0, n_reliable / cfg.gate.seasonal_min_history)
    score = (0.35 * accuracy + 0.30 * sufficiency
             + 0.20 * (forecastability or 0.0) + 0.15 * (data_quality or 0.0))
    if validation_skipped:
        score = min(score, 0.35)
    return float(np.clip(score, 0.0, 1.0))


def confidence_label(score: float) -> str:
    if score < 0.40:
        return "low"
    if score < 0.70:
        return "medium"
    return "high"


def generate(model: BaseModel, last_period: pd.Period, cfg: EngineConfig,
             confidence: float) -> pd.DataFrame:
    """Forecast `cfg.forecast.horizon` periods past `last_period`.

    Returns one row per future period with the TARGET-scale value (rate for
    Relative, per-day quantity for Absolute) and clipped, ordered intervals.
    """
    h = cfg.forecast.horizon
    inner, outer = cfg.forecast.interval_levels
    future = full_range(last_period + 1, last_period + h)

    point = np.asarray(model.predict(h), dtype=float)
    lo_i, up_i = model.prediction_interval(h, inner)
    lo_o, up_o = model.prediction_interval(h, outer)

    # clip at zero, then restore ordering invariants exactly
    point = np.clip(point, 0.0, None)
    lo_i, up_i = np.clip(lo_i, 0.0, None), np.clip(up_i, 0.0, None)
    lo_o, up_o = np.clip(lo_o, 0.0, None), np.clip(up_o, 0.0, None)
    lo_i = np.minimum(lo_i, point)
    lo_o = np.minimum(lo_o, lo_i)
    up_i = np.maximum(up_i, point)
    up_o = np.maximum(up_o, up_i)

    return pd.DataFrame({
        "period": [str(p) for p in future],
        "target_value": point,
        "lower_80": lo_i, "upper_80": up_i,
        "lower_95": lo_o, "upper_95": up_o,
        "confidence": confidence,
    })
