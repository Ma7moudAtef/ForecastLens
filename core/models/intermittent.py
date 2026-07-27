"""Intermittent-demand family — reached by classification, not competition.

Shared idea: stop forecasting "how much per period"; track how BIG a demand
event is when it happens and how OFTEN events happen. Croston carries a known
upward bias, SBA corrects it (the default), and TSB tracks demand
probability every period so the forecast decays toward zero during long
silences — the obsolescence model.
"""
from __future__ import annotations

import numpy as np

from core.models.base import BaseModel


class Croston(BaseModel):
    name = "Croston"
    n_params = 2
    min_history = 4
    _bias_factor = 1.0

    def __init__(self, alpha: float = 0.1):
        super().__init__()
        self.alpha = alpha

    def _fit(self, y, driver, period_index):
        alpha = self.alpha
        nz_idx = np.flatnonzero(y > 0)
        self.n_events_ = len(nz_idx)
        if self.n_events_ == 0:
            self.size_, self.interval_ = 0.0, 1.0
            return
        sizes = y[nz_idx].astype(float)
        intervals = np.diff(np.concatenate([[-1], nz_idx])).astype(float)
        # initialize at the event means (stable on short series), then smooth
        size = float(sizes.mean())
        interval = float(intervals.mean())
        for s, iv in zip(sizes, intervals):
            size += alpha * (s - size)
            interval += alpha * (iv - interval)
        self.size_, self.interval_ = size, max(interval, 1.0)

    def _rate(self) -> float:
        if self.n_events_ == 0:
            return 0.0
        return self._bias_factor * self.size_ / self.interval_

    def predict(self, horizon):
        return np.full(horizon, self._rate())

    def params(self):
        return {"alpha": self.alpha, "event_size": self.size_,
                "event_interval": self.interval_}

    def explain(self):
        return (f"Sporadic demand: roughly {self.size_:.4g} per event, "
                f"about every {self.interval_:.1f} periods.")


class SBA(Croston):
    """Syntetos-Boylan Approximation: Croston with the upward bias
    mathematically corrected by (1 − α/2). The default of the family."""

    name = "SBA"
    n_params = 2

    def __init__(self, alpha: float = 0.1):
        super().__init__(alpha)
        self._bias_factor = 1.0 - alpha / 2.0

    def explain(self):
        return (f"Sporadic demand: expected size {self.size_:.4g} about every "
                f"{self.interval_:.1f} periods, bias-corrected.")


class TSB(BaseModel):
    """Teunter-Syntetos-Babai: tracks the PROBABILITY of demand in any period
    and updates it every period, including empty ones — so the forecast decays
    toward zero during long silences. The model that handles obsolescence."""

    name = "TSB"
    n_params = 2
    min_history = 4

    def __init__(self, alpha_prob: float = 0.15, alpha_size: float = 0.1):
        super().__init__()
        self.alpha_prob = alpha_prob
        self.alpha_size = alpha_size

    def _fit(self, y, driver, period_index):
        occurred = (y > 0).astype(float)
        prob = float(occurred.mean()) if len(y) else 0.0
        nz = y[y > 0]
        size = float(nz.mean()) if len(nz) else 0.0
        for i, val in enumerate(y):
            prob += self.alpha_prob * (occurred[i] - prob)
            if occurred[i]:
                size += self.alpha_size * (float(val) - size)
        self.prob_, self.size_ = prob, size

    def predict(self, horizon):
        return np.full(horizon, self.prob_ * self.size_)

    def params(self):
        return {"alpha_prob": self.alpha_prob, "alpha_size": self.alpha_size,
                "demand_probability": self.prob_, "event_size": self.size_}

    def explain(self):
        if self.prob_ < 0.15:
            return (f"Demand probability has declined to "
                    f"{self.prob_:.0%} per period — the item may be phasing out.")
        return (f"Sporadic demand with a {self.prob_:.0%} chance of movement "
                f"each period, sized around {self.size_:.4g}.")


class ZeroForecast(BaseModel):
    """For series with no remaining signal: the honest forecast is zero."""

    name = "ZeroForecast"
    n_params = 0
    min_history = 1

    def _fit(self, y, driver, period_index):
        pass

    def predict(self, horizon):
        return np.zeros(horizon)

    def fitted_values(self):
        return np.zeros_like(self.y_)

    def explain(self):
        return "No demand signal remains; forecasting zero until movement returns."
