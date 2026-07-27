"""Baselines. These exist to be beaten — if nothing beats them, the series
has no learnable signal and the baseline is the honest answer."""
from __future__ import annotations

import numpy as np

from core.models.base import BaseModel


class Naive(BaseModel):
    name = "Naive"
    n_params = 0
    min_history = 1

    def _fit(self, y, driver, period_index):
        self.last_ = float(y[-1])

    def predict(self, horizon):
        return np.full(horizon, self.last_)

    def fitted_values(self):
        f = np.empty_like(self.y_)
        f[0] = np.nan
        f[1:] = self.y_[:-1]
        return f

    def params(self):
        return {"last_value": self.last_}

    def explain(self):
        return "No reliable pattern found; using the most recent actual."


class SeasonalNaive(BaseModel):
    name = "SeasonalNaive"
    n_params = 0
    requires_seasonality = True

    def __init__(self, seasonal_period: int):
        super().__init__()
        self.m = seasonal_period
        self.min_history = 2 * seasonal_period

    def _fit(self, y, driver, period_index):
        self.season_ = y[-self.m:]

    def predict(self, horizon):
        reps = int(np.ceil(horizon / self.m))
        return np.tile(self.season_, reps)[:horizon]

    def fitted_values(self):
        f = np.full_like(self.y_, np.nan)
        f[self.m:] = self.y_[:-self.m]
        return f

    def params(self):
        return {"seasonal_period": self.m}

    def explain(self):
        return ("Strong repeating pattern across the cycle; using the same "
                "period from the previous cycle.")


class Drift(BaseModel):
    name = "Drift"
    n_params = 1
    min_history = 2
    interval_grows = True

    def _fit(self, y, driver, period_index):
        self.last_ = float(y[-1])
        self.slope_ = float((y[-1] - y[0]) / (len(y) - 1))

    def predict(self, horizon):
        return self.last_ + self.slope_ * np.arange(1, horizon + 1)

    def fitted_values(self):
        f = np.empty_like(self.y_)
        f[0] = np.nan
        f[1:] = self.y_[:-1] + self.slope_
        return f

    def params(self):
        return {"slope_per_period": self.slope_}

    def explain(self):
        direction = "upward" if self.slope_ > 0 else "downward"
        return (f"Consistent long-term {direction} drift of "
                f"{abs(self.slope_):.4g} per period, extended forward.")


class Mean(BaseModel):
    """Average of all history, flat forward. Driver-weighted in Relative mode:
    the level equals Σ(rateᵢ·driverᵢ)/Σ(driverᵢ) = Σconsumption/Σdriver, so
    periods when the driver barely ran do not distort the average."""

    name = "Mean"
    n_params = 1
    min_history = 2
    supports_driver_weighting = True

    def _fit(self, y, driver, period_index):
        self.driver_weighted_ = False
        if driver is not None:
            w = np.nan_to_num(driver, nan=0.0)
            if w.sum() > 0:
                self.level_ = float(np.sum(y * w) / w.sum())
                self.driver_weighted_ = True
                return
        self.level_ = float(np.mean(y))

    def predict(self, horizon):
        return np.full(horizon, self.level_)

    def params(self):
        return {"level": self.level_, "driver_weighted": self.driver_weighted_}

    def explain(self):
        if self.driver_weighted_:
            return ("Consumption rate is stable around its historical average, "
                    "weighted by how much the driver actually ran each period.")
        return "Consumption is stable around its historical average."
