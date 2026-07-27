"""Domain anchors — not time-series models. They inject knowledge the history
does not contain, and they are what rescues the cold-start third of the
catalog."""
from __future__ import annotations

import numpy as np

from core.models.base import BaseModel


class StandardRateAnchor(BaseModel):
    """Relative mode only: the engineered standard rate from consumption_figs
    is the forecast. When the standard beats every fitted model, that is a
    powerful, credible message — and actual-vs-standard is a KPI in itself."""

    name = "StandardRateAnchor"
    n_params = 0
    min_history = 0

    def __init__(self, std_rate: float):
        super().__init__()
        self.std_rate = float(std_rate)

    def fit(self, y, driver=None, period_index=None):
        # anchors accept any history length, including none
        self.y_ = np.asarray(y, dtype=float) if y is not None else np.array([])
        self._fit(self.y_, driver, period_index)
        self.resid_std_ = self._residual_std(self.y_) if len(self.y_) > 1 else 0.0
        return self

    def _fit(self, y, driver, period_index):
        pass

    def predict(self, horizon):
        return np.full(horizon, self.std_rate)

    def fitted_values(self):
        return np.full_like(self.y_, self.std_rate)

    def params(self):
        return {"std_rate": self.std_rate}

    def explain(self):
        return ("Insufficient stable history; using the engineered standard "
                "consumption rate.")


class CategoryPrior(BaseModel):
    """Cold start: a new or thin item inherits the pooled behaviour of its
    category siblings (level 3, then 2, then 1). The prior value is computed
    by the selection layer from sibling series and injected here."""

    name = "CategoryPrior"
    n_params = 0
    min_history = 0

    def __init__(self, prior_value: float, category_level: int, n_siblings: int,
                 category_name: str = ""):
        super().__init__()
        self.prior_value = float(prior_value)
        self.category_level = category_level
        self.n_siblings = n_siblings
        self.category_name = category_name

    def fit(self, y, driver=None, period_index=None):
        self.y_ = np.asarray(y, dtype=float) if y is not None else np.array([])
        self._fit(self.y_, driver, period_index)
        self.resid_std_ = self._residual_std(self.y_) if len(self.y_) > 1 else 0.0
        return self

    def _fit(self, y, driver, period_index):
        pass

    def predict(self, horizon):
        return np.full(horizon, self.prior_value)

    def fitted_values(self):
        return np.full_like(self.y_, self.prior_value)

    def params(self):
        return {"prior_value": self.prior_value,
                "category_level": self.category_level,
                "n_siblings": self.n_siblings}

    def explain(self):
        n_hist = len(self.y_) if self.y_ is not None else 0
        return (f"Only {n_hist} period(s) of history; using the average "
                f"behaviour of {self.n_siblings} similar item(s) in "
                f"category '{self.category_name}'.")
