"""Models 20–22: forecasting from the operating context, not only the past.

These three compete on exactly the same terms as everything else — same
rolling-origin folds, same MASE ranking, same simplicity tie-break (guard
G3). They earn no protection for being newer or cleverer. What they add is
the ability to say "next month two units run together, and this material is
heavier when that happens", which no history-only model can express.

Each one refuses to fit when its own preconditions are not met, and a refusal
is an ordinary disqualification: the run continues with the remaining
candidates (guard G5).

    20  FixedPlusVariable  — a standing component plus a component that
                             scales with how much actually runs.
    21  RegimeConditional  — a separate level for each operating pattern.
    22  ContextRegression  — a small, AIC-selected regression on the context
                             features that survive a collinearity check.
"""
from __future__ import annotations

import numpy as np
from scipy import optimize as _opt

from core.context.features import (
    CALENDAR_PREFIX,
    OTHER_REGIME,
    humanize_regime,
    pool_rare_regimes,
)
from core.models.base import BaseModel

#: minimum relative variation in the driver before a fixed/variable split is
#: identifiable at all — with a flat driver the two components are the same
#: number wearing different hats
DEFAULT_MIN_DRIVER_CV = 0.10


def _needs_context(window, name: str) -> None:
    if window is None:
        raise ValueError(f"{name} needs operating context and none was supplied")


def _pooled(labels: np.ndarray, min_obs: int) -> np.ndarray:
    import pandas as pd

    return pool_rare_regimes(pd.Series(np.asarray(labels, dtype=object)),
                             min_obs).to_numpy(dtype=object)


class FixedPlusVariable(BaseModel):
    """Consumption = a standing amount + an amount proportional to activity.

    Setup losses, standing cleaning, heating and idle draw do not disappear
    when output halves — so consumption per unit of output rises as output
    falls. Fitting the two components separately reproduces that; a single
    average cannot.

    On a Relative series the target is a RATE, so the relationship is
    ``rate = fixed / driver + variable`` and the model regresses on 1/driver.
    On an Absolute series the target is a quantity, regressed on how much the
    whole system ran. Both coefficients are constrained to be non-negative:
    a negative standing consumption is not a thing.
    """

    name = "FixedPlusVariable"
    n_params = 2
    min_history = 8
    uses_context = True

    def __init__(self, target_is_rate: bool = True,
                 min_driver_cv: float = DEFAULT_MIN_DRIVER_CV):
        super().__init__()
        self.target_is_rate = target_is_rate
        self.min_driver_cv = min_driver_cv
        self._window = None

    def set_context(self, window) -> None:
        self._window = window

    # --- the regressor -------------------------------------------------------
    def _activity(self, window, future: bool) -> np.ndarray:
        d = window.future_driver if future else window.driver
        s = window.future_system_driver if future else window.system_driver
        base = np.asarray(d if self.target_is_rate else s, dtype=float)
        return base

    def _design(self, activity: np.ndarray) -> np.ndarray:
        """Column that carries the FIXED component. For a rate target the
        fixed part is spread over the driver, so its regressor is 1/driver;
        for a quantity target it is a plain intercept."""
        if not self.target_is_rate:
            return np.ones_like(activity)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv = np.where(activity > 0, 1.0 / activity, np.nan)
        return inv

    def _fit(self, y, driver, period_index):
        _needs_context(self._window, self.name)
        w = self._window
        activity = self._activity(w, future=False)
        if len(activity) != len(y):
            raise ValueError("context is not aligned with the series")
        fixed_col = self._design(activity)
        var_col = np.ones_like(activity) if self.target_is_rate else activity

        usable = np.isfinite(fixed_col) & np.isfinite(var_col) & np.isfinite(y)
        if usable.sum() < self.min_history:
            raise ValueError(
                f"{self.name} needs {self.min_history} periods with a usable "
                f"driver, got {int(usable.sum())}")
        act = activity[usable]
        if act.mean() <= 0 or (act.std() / abs(act.mean())) < self.min_driver_cv:
            raise ValueError(
                "the driver barely varies, so a fixed and a variable "
                "component cannot be told apart")

        A = np.column_stack([fixed_col[usable], var_col[usable]])
        coef, _ = _opt.nnls(A, y[usable])
        self.fixed_, self.variable_ = float(coef[0]), float(coef[1])
        self._usable = usable
        self._fixed_col = fixed_col
        self._var_col = var_col

    def predict(self, horizon):
        w = self._window
        activity = self._activity(w, future=True)
        if len(activity) < horizon:
            # a shorter plan than the horizon cannot be extrapolated honestly
            raise ValueError("the driver plan is shorter than the horizon")
        activity = activity[:horizon]
        fixed_col = self._design(activity)
        var_col = np.ones_like(activity) if self.target_is_rate else activity
        out = self.fixed_ * fixed_col + self.variable_ * var_col
        # a planned-idle period has no rate to speak of; fall back to the
        # average of what the model expects when things do run
        finite = out[np.isfinite(out)]
        return np.where(np.isfinite(out), out,
                        float(finite.mean()) if len(finite) else self.variable_)

    def fitted_values(self):
        out = self.fixed_ * self._fixed_col + self.variable_ * self._var_col
        return np.where(self._usable, out, np.nan)

    def params(self):
        return {"fixed": self.fixed_, "variable": self.variable_,
                "target_is_rate": self.target_is_rate}

    def _standing_share(self) -> float:
        """How much of a typical period's consumption is the standing part.
        Computed from what actually ran, because a coefficient per period and
        a coefficient per unit of driver cannot simply be added together."""
        fixed = self.fixed_ * float(np.mean(self._fixed_col[self._usable]))
        variable = self.variable_ * float(np.mean(self._var_col[self._usable]))
        total = fixed + variable
        return (fixed / total) if total > 0 else 0.0

    def explain(self):
        share = self._standing_share()
        if self.target_is_rate:
            return (f"Consumption splits into a standing part that does not "
                    f"change with output ({self.fixed_:,.4g} per period, about "
                    f"{share:.0%} of a typical period's use) and a part that "
                    f"scales with it ({self.variable_:,.4g} per unit of "
                    f"driver). That is why the rate rises when the line runs "
                    f"slowly: the standing part is spread over less output.")
        return (f"Consumption splits into a standing part ({self.fixed_:,.4g} "
                f"per period, about {share:.0%} of a typical period's use) "
                f"and a part that scales with how much the plant runs "
                f"({self.variable_:,.4g} per unit).")


class RegimeConditional(BaseModel):
    """A separate level for each operating pattern.

    When a material behaves like one thing while a single unit runs and
    another thing while two run together, an average of the two is right for
    neither. This keeps one level per pattern and picks the one the planned
    period will actually be in.
    """

    name = "RegimeConditional"
    #: at least two levels; the fitted count replaces this once known. The
    #: static value is what the simplicity tie-break sees, so a plain average
    #: wins any tie against it — which is the intent.
    n_params = 3
    min_history = 12
    uses_context = True

    def __init__(self, min_regime_obs: int = 4):
        super().__init__()
        self.min_regime_obs = min_regime_obs
        self._window = None

    def set_context(self, window) -> None:
        self._window = window

    def _fit(self, y, driver, period_index):
        _needs_context(self._window, self.name)
        labels = np.asarray(self._window.regimes, dtype=object)
        if len(labels) != len(y):
            raise ValueError("context is not aligned with the series")
        pooled = _pooled(labels, self.min_regime_obs)
        levels: dict[str, float] = {}
        counts: dict[str, int] = {}
        for name in dict.fromkeys(pooled):
            mask = pooled == name
            if mask.sum() < self.min_regime_obs:
                continue
            levels[str(name)] = float(np.mean(y[mask]))
            counts[str(name)] = int(mask.sum())
        if len(levels) < 2:
            raise ValueError(
                f"fewer than two operating patterns have {self.min_regime_obs} "
                "or more periods, so separate levels cannot be estimated")
        self.levels_ = levels
        self.counts_ = counts
        self.default_ = float(np.mean(y))
        self.n_params = len(levels)
        self._pooled = pooled
        self.unseen_ = 0

    def _level_for(self, label) -> float:
        key = str(label)
        if key in self.levels_:
            return self.levels_[key]
        if OTHER_REGIME in self.levels_:
            return self.levels_[OTHER_REGIME]
        return self.default_

    def predict(self, horizon):
        future = np.asarray(self._window.future_regimes, dtype=object)
        if len(future) < horizon:
            raise ValueError("the driver plan is shorter than the horizon")
        future = future[:horizon]
        self.unseen_ = int(sum(1 for f in future if str(f) not in self.levels_))
        return np.array([self._level_for(f) for f in future], dtype=float)

    def fitted_values(self):
        return np.array([self._level_for(p) for p in self._pooled], dtype=float)

    def params(self):
        return {"levels": dict(self.levels_), "counts": dict(self.counts_),
                "unseen_future_regimes": self.unseen_}

    def explain(self):
        ordered = sorted(self.levels_.items(), key=lambda kv: -kv[1])
        high, low = ordered[0], ordered[-1]
        ratio = (high[1] / low[1]) if low[1] > 0 else float("inf")
        lead = (f"This material behaves differently depending on what else is "
                f"running: {high[1]:,.4g} under {humanize_regime(high[0])} "
                f"against {low[1]:,.4g} under {humanize_regime(low[0])}")
        if np.isfinite(ratio):
            lead += f" — {ratio:.1f}× the difference"
        lead += (f". The forecast uses the level of whichever pattern the "
                 f"driver plan says each future period will be in.")
        if self.unseen_:
            lead += (f" {self.unseen_} planned period(s) fall under a pattern "
                     "never seen before, so the overall average is used for "
                     "those.")
        return lead


class ContextRegression(BaseModel):
    """A small regression on the operating conditions of the period.

    Forward selection by AIC, one regressor per `observations_per_regressor`
    periods, and any candidate that is too collinear with what is already in
    the model is rejected. The result is deliberately tiny: two or three
    regressors on twenty-odd observations, never a kitchen sink.
    """

    name = "ContextRegression"
    #: intercept plus at least one regressor; see RegimeConditional on why the
    #: static value matters more than the fitted one
    n_params = 3
    min_history = 20
    uses_context = True

    def __init__(self, observations_per_regressor: int = 8,
                 max_vif: float = 5.0):
        super().__init__()
        self.observations_per_regressor = observations_per_regressor
        self.max_vif = max_vif
        self._window = None

    def set_context(self, window) -> None:
        self._window = window

    # --- fitting helpers -----------------------------------------------------
    @staticmethod
    def _ols(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ coef
        return coef, float(np.sum(resid ** 2))

    @staticmethod
    def _aic(rss: float, n: int, k: int) -> float:
        if rss <= 0:
            rss = 1e-12
        return n * np.log(rss / n) + 2.0 * k

    def _vif(self, design: np.ndarray, candidate: np.ndarray) -> float:
        """Variance inflation of `candidate` against the regressors already
        in the model. 1 = independent; large = it says nothing new.
        `design` carries the intercept, as a VIF regression should."""
        if design.shape[1] <= 1:
            return 1.0
        _, rss = self._ols(design, candidate)
        total = float(np.sum((candidate - candidate.mean()) ** 2))
        if total <= 0:
            return float("inf")
        r2 = 1.0 - rss / total
        if r2 >= 1.0 - 1e-9:
            return float("inf")
        return 1.0 / (1.0 - r2)

    def _fit(self, y, driver, period_index):
        _needs_context(self._window, self.name)
        w = self._window
        X_all = np.asarray(w.X, dtype=float)
        if X_all.shape[0] != len(y):
            raise ValueError("context is not aligned with the series")
        if X_all.shape[1] == 0:
            raise ValueError("no usable context features for this series")

        n = len(y)
        budget = max(1, n // self.observations_per_regressor)
        intercept = np.ones((n, 1))
        chosen: list[int] = []
        design = intercept
        _, rss = self._ols(design, y)
        best_aic = self._aic(rss, n, 1)
        rejected: dict[str, str] = {}

        while len(chosen) < budget:
            best = None
            for j in range(X_all.shape[1]):
                if j in chosen:
                    continue
                column = X_all[:, j]
                if not np.all(np.isfinite(column)) or np.std(column) <= 1e-12:
                    rejected.setdefault(w.names[j], "it never changes")
                    continue
                vif = self._vif(design, column)
                if vif > self.max_vif:
                    rejected[w.names[j]] = (
                        "it repeats information already in the model")
                    continue
                trial = np.column_stack([design, column])
                _, trial_rss = self._ols(trial, y)
                aic = self._aic(trial_rss, n, trial.shape[1])
                if best is None or aic < best[0]:
                    best = (aic, j, trial)
            if best is None or best[0] >= best_aic - 1e-9:
                break
            best_aic, j, design = best[0], best[1], best[2]
            chosen.append(j)

        if not chosen:
            raise ValueError(
                "no operating condition improved on a plain average")

        self.selected_ = chosen
        self.feature_names_ = [w.names[j] for j in chosen]
        self.rejected_features_ = {k: v for k, v in rejected.items()
                                   if k not in self.feature_names_}
        self.coef_, rss = self._ols(design, y)
        self.n_params = design.shape[1]
        self._design = design
        total = float(np.sum((y - y.mean()) ** 2))
        self.r2_ = float(1.0 - rss / total) if total > 0 else 0.0

    def predict(self, horizon):
        w = self._window
        future = np.asarray(w.future_X, dtype=float)
        if future.shape[0] < horizon:
            raise ValueError("the driver plan is shorter than the horizon")
        block = future[:horizon][:, self.selected_] if self.selected_ \
            else np.zeros((horizon, 0))
        design = np.column_stack([np.ones(horizon), block])
        out = design @ self.coef_
        return np.where(np.isfinite(out), out, float(self.coef_[0]))

    def fitted_values(self):
        return self._design @ self.coef_

    def params(self):
        return {"features": list(self.feature_names_),
                "coefficients": [float(c) for c in self.coef_],
                "r2": self.r2_}

    def explain(self):
        readable = ", ".join(feature_words(f) for f in self.feature_names_)
        share = f"{max(0.0, self.r2_):.0%}"
        return (f"Consumption tracks the operating conditions of the period — "
                f"{readable} — which together explain about {share} of the "
                "variation. The forecast reads those conditions from the "
                "driver plan for each future period.")


#: plain words for the derived feature names, used in every explanation a
#: planner reads
FEATURE_WORDS = {
    "n_active": "how many units are running",
    "is_solo": "whether this unit runs alone",
    "own_share": "this unit's share of total output",
    "system_driver": "how much the whole plant runs",
    "utilization": "how hard this unit is pushed",
    "mix_entropy": "how evenly output is spread across units",
}


def feature_words(name: str) -> str:
    """A context feature named the way a planner would say it. User-supplied
    calendar factors keep their own names, minus the internal prefix."""
    if name in FEATURE_WORDS:
        return FEATURE_WORDS[name]
    return name[len(CALENDAR_PREFIX):].replace("_", " ") \
        if name.startswith(CALENDAR_PREFIX) else name
