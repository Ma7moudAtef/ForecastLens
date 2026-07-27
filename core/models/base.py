"""The one contract every model implements.

The competition loop stays generic; adding a model touches no orchestration
code. Every fit is wrapped in try/except by the CALLER (selection layer): a
model that fails to converge is disqualified from that series' competition —
it never aborts the run.

Prediction intervals are residual-based for every model: point ± z·σ, with σ
the in-sample one-step residual standard deviation and an optional √h growth
for trend-capable models. Uniform construction guarantees the interval
ordering property (lower95 ≤ lower80 ≤ point ≤ upper80 ≤ upper95). Zero
clipping happens at forecast generation, not here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
from scipy import stats as _stats


class BaseModel(ABC):
    name: str = "?"
    #: parameters the model estimates — the simplicity tie-break metric
    n_params: int = 0
    #: minimum observations the model can honestly be fitted on
    min_history: int = 1
    requires_seasonality: bool = False
    supports_driver_weighting: bool = False
    #: trend-capable models widen intervals with the horizon
    interval_grows: bool = False

    def __init__(self) -> None:
        self.y_: np.ndarray | None = None
        self.resid_std_: float = 0.0

    # --- lifecycle -----------------------------------------------------------
    def fit(self, y, driver=None, period_index=None) -> "BaseModel":
        y = np.asarray(y, dtype=float)
        if len(y) < self.min_history:
            raise ValueError(
                f"{self.name} needs >= {self.min_history} observations, got {len(y)}")
        self.y_ = y
        d = None if driver is None else np.asarray(driver, dtype=float)
        self._fit(y, d, period_index)
        self.resid_std_ = self._residual_std(y)
        return self

    @abstractmethod
    def _fit(self, y: np.ndarray, driver: np.ndarray | None, period_index) -> None:
        ...

    @abstractmethod
    def predict(self, horizon: int) -> np.ndarray:
        ...

    def fitted_values(self) -> np.ndarray:
        """In-sample one-step predictions aligned with y (NaN where undefined).
        Default: each point predicted by the model's final flat level —
        subclasses override where a real one-step fit exists."""
        point = self.predict(1)[0]
        return np.full_like(self.y_, point, dtype=float)

    def _residual_std(self, y: np.ndarray) -> float:
        fitted = self.fitted_values()
        resid = y - fitted
        resid = resid[~np.isnan(resid)]
        if len(resid) < 2:
            return float(np.std(y)) if len(y) > 1 else 0.0
        return float(np.std(resid, ddof=0))

    def prediction_interval(self, horizon: int, level: float) -> tuple[np.ndarray, np.ndarray]:
        point = self.predict(horizon)
        z = _stats.norm.ppf(0.5 + level / 2.0)
        scale = np.sqrt(np.arange(1, horizon + 1, dtype=float)) if self.interval_grows \
            else np.ones(horizon)
        half = z * self.resid_std_ * scale
        return point - half, point + half

    def params(self) -> dict:
        return {}

    @abstractmethod
    def explain(self) -> str:
        """One plain sentence a planner can read. No jargon, no metric dumps."""
        ...
