"""Forecast error metrics.

MASE is the ranking metric — the only scale-free metric that survives zeros
and very small rate values. MAPE and sMAPE are computed for display but must
NEVER be used for ranking (rates are ~0.003 and 60% of series contain zeros).
"""
from __future__ import annotations

import numpy as np


def mae(actual: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - forecast)))


def rmse(actual: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - forecast) ** 2)))


def mape(actual: np.ndarray, forecast: np.ndarray) -> float | None:
    """Display only. Undefined where actuals contain zeros — those points are
    excluded; None when every actual is zero."""
    mask = actual != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((actual[mask] - forecast[mask]) / actual[mask])) * 100)


def smape(actual: np.ndarray, forecast: np.ndarray) -> float | None:
    """Display only."""
    denom = (np.abs(actual) + np.abs(forecast)) / 2.0
    mask = denom != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs(actual[mask] - forecast[mask]) / denom[mask]) * 100)


def naive_insample_mae(train: np.ndarray) -> float:
    """The MASE denominator: in-sample one-step naive error on the train set."""
    if len(train) < 2:
        return 0.0
    return float(np.mean(np.abs(np.diff(train))))


def mase(actual: np.ndarray, forecast: np.ndarray, train: np.ndarray) -> float:
    """Mean Absolute Scaled Error. A flat-line-naive with zero in-sample error
    (constant train series) makes the scale degenerate: 0/0 → 0.0 (perfect),
    otherwise infinity (any error is infinitely worse than perfect naive)."""
    scale = naive_insample_mae(train)
    err = mae(actual, forecast)
    if scale == 0.0:
        return 0.0 if err == 0.0 else float("inf")
    return err / scale
