"""Exponential smoothing family — the workhorses.

Every observation counts, with influence decaying the further back it is;
the models LEARN the decay rate from the data. Known, accepted limitation:
statsmodels smoothing cannot be driver-weighted. When a Relative series has
driver CV > 0.5 the selection layer warns that unweighted smoothing may be
biased and always keeps the weighted-average family in the candidate set as
a check.
"""
from __future__ import annotations

import warnings

import numpy as np

from core.models.base import BaseModel


def _fit_es(y, **kwargs):
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ExponentialSmoothing(y, initialization_method="estimated", **kwargs)
        return model.fit(optimized=True)


class _StatsmodelsSmoothing(BaseModel):
    """Shared plumbing for the ExponentialSmoothing-backed models."""

    def _es_kwargs(self) -> dict:
        return {}

    def _fit(self, y, driver, period_index):
        self.res_ = _fit_es(y, **self._es_kwargs())

    def predict(self, horizon):
        return np.asarray(self.res_.forecast(horizon), dtype=float)

    def fitted_values(self):
        return np.asarray(self.res_.fittedvalues, dtype=float)

    def params(self):
        p = self.res_.params
        return {k: float(v) for k, v in p.items()
                if k in ("smoothing_level", "smoothing_trend",
                         "smoothing_seasonal", "damping_trend")
                and v == v}


class SES(_StatsmodelsSmoothing):
    name = "SES"
    n_params = 1
    min_history = 5

    def explain(self):
        alpha = self.params().get("smoothing_level", 0.0)
        memory = "recent periods weighted much more heavily" if alpha > 0.5 else \
            "a long memory of past periods"
        return f"Stable consumption with no clear direction; {memory}."


class Holt(_StatsmodelsSmoothing):
    name = "Holt"
    n_params = 2
    min_history = 10
    interval_grows = True

    def _es_kwargs(self):
        return {"trend": "add"}

    def _slope(self) -> float:
        f = self.predict(2)
        return float(f[1] - f[0])

    def explain(self):
        s = self._slope()
        d = "upward" if s > 0 else "downward"
        return f"Sustained {d} trend of {abs(s):.4g} per period detected."


class DampedHolt(_StatsmodelsSmoothing):
    name = "DampedHolt"
    n_params = 3
    min_history = 10
    interval_grows = True

    def _es_kwargs(self):
        return {"trend": "add", "damped_trend": True}

    def explain(self):
        return ("Recent trend detected but damped — long-horizon extrapolation "
                "is deliberately conservative.")


class HoltWinters(_StatsmodelsSmoothing):
    """Additive when the seasonal swing is a fixed amount; multiplicative when
    it is a percentage of the level. Both are tried, the better AICc wins."""

    name = "HoltWinters"
    n_params = 4
    requires_seasonality = True
    interval_grows = True

    def __init__(self, seasonal_period: int):
        super().__init__()
        self.m = seasonal_period
        self.min_history = 2 * seasonal_period

    def _fit(self, y, driver, period_index):
        candidates = ["add"]
        if np.all(y > 0):
            candidates.append("mul")
        best = None
        for seasonal in candidates:
            try:
                res = _fit_es(y, trend="add", damped_trend=True,
                              seasonal=seasonal, seasonal_periods=self.m)
                if best is None or res.aicc < best[0].aicc:
                    best = (res, seasonal)
            except Exception:
                continue
        if best is None:
            raise RuntimeError("Holt-Winters failed for both seasonal forms")
        self.res_, self.seasonal_form_ = best

    def explain(self):
        form = "fixed-amount" if self.seasonal_form_ == "add" else "percentage"
        try:
            season = np.asarray(self.res_.season[-self.m:], dtype=float)
            peak = int(np.argmax(season)) + 1
            return (f"Repeating pattern across the {self.m}-period cycle "
                    f"({form} swings), peaking around period {peak} of the cycle.")
        except Exception:
            return (f"Repeating pattern across the {self.m}-period cycle "
                    f"({form} swings).")


class ETS(_StatsmodelsSmoothing):
    """Automatic smoothing-family selection: valid combinations of trend and
    seasonality are tried and the best information criterion (AICc) wins.
    Restricted to non-seasonal forms below two full cycles."""

    name = "ETS"
    min_history = 15

    def __init__(self, seasonal_period: int, allow_seasonal: bool):
        super().__init__()
        self.m = seasonal_period
        self.allow_seasonal = allow_seasonal
        self.n_params = 1  # updated after fit to the chosen form's count

    def _fit(self, y, driver, period_index):
        combos: list[dict] = [
            {},
            {"trend": "add"},
            {"trend": "add", "damped_trend": True},
        ]
        if self.allow_seasonal and len(y) >= 2 * self.m:
            combos += [
                {"trend": None, "seasonal": "add", "seasonal_periods": self.m},
                {"trend": "add", "damped_trend": True, "seasonal": "add",
                 "seasonal_periods": self.m},
            ]
            if np.all(y > 0):
                combos.append({"trend": "add", "damped_trend": True,
                               "seasonal": "mul", "seasonal_periods": self.m})
        best, best_kwargs = None, None
        for kwargs in combos:
            try:
                res = _fit_es(y, **kwargs)
                if best is None or res.aicc < best.aicc:
                    best, best_kwargs = res, kwargs
            except Exception:
                continue
        if best is None:
            raise RuntimeError("every ETS candidate form failed to fit")
        self.res_, self.form_ = best, best_kwargs
        self.n_params = 1 + (1 if self.form_.get("trend") else 0) \
            + (1 if self.form_.get("damped_trend") else 0) \
            + (1 if self.form_.get("seasonal") else 0)
        self.interval_grows = bool(self.form_.get("trend"))

    def form_description(self) -> str:
        trend = self.form_.get("trend")
        damped = self.form_.get("damped_trend")
        seasonal = self.form_.get("seasonal")
        t = "no trend" if not trend else ("damped trend" if damped else "additive trend")
        s = "no seasonality" if not seasonal else \
            ("additive seasonality" if seasonal == "add" else "multiplicative seasonality")
        return f"{t}, {s}"

    def explain(self):
        return (f"Automatic smoothing selection chose the best-fitting form: "
                f"{self.form_description()}.")
