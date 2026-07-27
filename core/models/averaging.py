"""Averaging windows — MA and WMA, both driver-weighted in Relative mode.

Trap 2: with unequal drivers the weighted result differs from the arithmetic
mean and equals Σconsumption/Σdriver over the window. Driver CV in the sample
is 0.97, so this is a large effect, not a rounding detail.
"""
from __future__ import annotations

import numpy as np

from core.models.base import BaseModel


class MovingAverage(BaseModel):
    """Average of the last k periods, driver-weighted when a driver exists:
    level = Σ(yᵢ·Pᵢ)/Σ(Pᵢ) over the window = ΣCᵢ/ΣPᵢ."""

    name = "MovingAverage"
    n_params = 1
    supports_driver_weighting = True

    def __init__(self, window: int):
        super().__init__()
        self.window = window
        self.min_history = window + 1

    def _level(self, y, w):
        if w is not None and np.nansum(w) > 0:
            w = np.nan_to_num(w, nan=0.0)
            return float(np.sum(y * w) / w.sum())
        return float(np.mean(y))

    def _fit(self, y, driver, period_index):
        k = self.window
        self.driver_weighted_ = driver is not None and np.nansum(driver[-k:]) > 0
        self.level_ = self._level(y[-k:], None if driver is None else driver[-k:])
        self._driver = driver

    def predict(self, horizon):
        return np.full(horizon, self.level_)

    def fitted_values(self):
        y, k, d = self.y_, self.window, self._driver
        f = np.full_like(y, np.nan)
        for i in range(k, len(y)):
            f[i] = self._level(y[i - k:i], None if d is None else d[i - k:i])
        return f

    def params(self):
        return {"window": self.window, "level": self.level_,
                "driver_weighted": self.driver_weighted_}

    def explain(self):
        tail = (" Each period is weighted by its driver volume, so low-activity "
                "periods do not distort the average.") if self.driver_weighted_ else ""
        return (f"Average of the last {self.window} periods; older history is "
                f"no longer representative.{tail}")


class WeightedMovingAverage(BaseModel):
    """Moving average with linear recency weights ON TOP of driver weights:
    level = Σ(wᵢ·yᵢ·Pᵢ)/Σ(wᵢ·Pᵢ). Without a driver: Σ(wᵢ·yᵢ)/Σ(wᵢ)."""

    name = "WeightedMovingAverage"
    n_params = 2
    supports_driver_weighting = True

    def __init__(self, window: int):
        super().__init__()
        self.window = window
        self.min_history = window + 1
        self.recency_ = np.arange(1, window + 1, dtype=float)  # oldest → newest

    def _level(self, y, driver):
        w = self.recency_.copy()
        if driver is not None and np.nansum(driver) > 0:
            w = w * np.nan_to_num(driver, nan=0.0)
        if w.sum() == 0:
            return float(np.mean(y))
        return float(np.sum(w * y) / w.sum())

    def _fit(self, y, driver, period_index):
        k = self.window
        self.driver_weighted_ = driver is not None and np.nansum(driver[-k:]) > 0
        self.level_ = self._level(y[-k:], None if driver is None else driver[-k:])
        self._driver = driver

    def predict(self, horizon):
        return np.full(horizon, self.level_)

    def fitted_values(self):
        y, k, d = self.y_, self.window, self._driver
        f = np.full_like(y, np.nan)
        for i in range(k, len(y)):
            f[i] = self._level(y[i - k:i], None if d is None else d[i - k:i])
        return f

    def params(self):
        return {"window": self.window, "level": self.level_,
                "driver_weighted": self.driver_weighted_}

    def explain(self):
        return (f"Average of the last {self.window} periods weighted toward "
                "recent ones, which better reflect current conditions.")
