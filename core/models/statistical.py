"""Statistical models: Theta and (optional, gated) ARIMA."""
from __future__ import annotations

import warnings

import numpy as np

from core.models.base import BaseModel


class Theta(BaseModel):
    """Classic Theta(0,2): the series is split into a heavily-smoothed line
    capturing the long-run direction (theta=0, the linear regression) and an
    exaggerated line capturing short-run movement (theta=2). The theta=2 line
    is forecast with SES, the theta=0 line extrapolated linearly, and the two
    are averaged. Won the M3 competition; extremely hard to beat on short
    monthly business series."""

    name = "Theta"
    n_params = 2
    min_history = 8
    interval_grows = True

    def _fit(self, y, driver, period_index):
        n = len(y)
        t = np.arange(n, dtype=float)
        # theta=0 line: OLS trend
        self.b1_, self.b0_ = np.polyfit(t, y, 1)
        trend_line = self.b0_ + self.b1_ * t
        # theta=2 line: 2y - trend, forecast by SES
        theta2 = 2.0 * y - trend_line
        from statsmodels.tsa.holtwinters import SimpleExpSmoothing
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.ses_ = SimpleExpSmoothing(
                theta2, initialization_method="estimated").fit(optimized=True)
        self.n_ = n
        self._trend_line = trend_line

    def predict(self, horizon):
        h = np.arange(1, horizon + 1, dtype=float)
        line0 = self.b0_ + self.b1_ * (self.n_ - 1 + h)
        line2 = np.asarray(self.ses_.forecast(horizon), dtype=float)
        return 0.5 * (line0 + line2)

    def fitted_values(self):
        f2 = np.asarray(self.ses_.fittedvalues, dtype=float)
        return 0.5 * (self._trend_line + f2)

    def params(self):
        return {"trend_slope": float(self.b1_),
                "ses_alpha": float(self.ses_.params.get("smoothing_level", np.nan))}

    def explain(self):
        return ("Balances the long-term direction of the series against its "
                "recent movement.")


class ARIMA(BaseModel):
    """Models the series through its own past values and past errors, after
    differencing away trend. Small fixed order grid selected by AICc — no
    auto-arima dependency. Gated: >= 24 periods and off by default."""

    name = "ARIMA"
    min_history = 24
    interval_grows = True

    _GRID = [(p, d, q)
             for p in (0, 1, 2) for d in (0, 1) for q in (0, 1, 2)
             if (p, d, q) != (0, 0, 0)]

    def _fit(self, y, driver, period_index):
        from statsmodels.tsa.arima.model import ARIMA as SmARIMA
        best, best_order = None, None
        for order in self._GRID:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    res = SmARIMA(y, order=order,
                                  enforce_stationarity=False,
                                  enforce_invertibility=False).fit()
                if best is None or res.aicc < best.aicc:
                    best, best_order = res, order
            except Exception:
                continue
        if best is None:
            raise RuntimeError("no ARIMA order converged")
        self.res_, self.order_ = best, best_order
        p, d, q = best_order
        self.n_params = p + q + (1 if d == 0 else 0) + 1

    def predict(self, horizon):
        return np.asarray(self.res_.forecast(horizon), dtype=float)

    def fitted_values(self):
        f = np.asarray(self.res_.fittedvalues, dtype=float)
        d = self.order_[1]
        if d > 0 and len(f) > d:  # differenced fits are meaningless at the start
            f = f.copy()
            f[:d] = np.nan
        return f

    def params(self):
        return {"order": self.order_}

    def explain(self):
        p, d, q = self.order_
        parts = []
        if p:
            parts.append("recent deviations tend to carry into the next period")
        if d:
            parts.append("the underlying level shifts over time")
        if q:
            parts.append("recent forecast errors are corrected")
        detail = "; ".join(parts) if parts else "simple autocorrelation structure"
        return f"The series' own past predicts its future: {detail}."
