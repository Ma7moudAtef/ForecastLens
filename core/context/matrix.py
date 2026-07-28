"""Per-series context arrays, aligned to the fitting target.

`features.derive()` produces one row per (period, unit, stream) for the whole
dataset. A model needs something narrower: the rows for ITS combination, in
the same order as its own observations, plus the rows for the periods it is
about to forecast.

Everything here is knowable before the forecast period happens (guard G1) —
the future rows come from the driver PLAN, which the planner supplies in
advance. If a horizon period has no plan at all, `known_future` is False and
the context models are never offered: a model that needs a regressor nobody
can supply is a model that cannot be used.

A period where this combination has no driver row is not a hole in the data.
It means the combination did not run, which is itself an operating
condition — so it is filled with that period's own conditions (what else was
running, how much in total) and a zero own-driver, rather than deleting the
feature.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.context.features import (
    CALENDAR_PREFIX,
    DERIVED_FEATURES,
    IDLE_REGIME,
    ContextFrame,
)

#: value used when a combination did not run in a period
_ABSENT = {"n_active": 0.0, "is_solo": 0.0, "own_share": 0.0,
           "system_driver": 0.0, "utilization": 0.0, "mix_entropy": 0.0,
           "driver_qty": 0.0}


@dataclass(frozen=True)
class ContextWindow:
    """What a model is allowed to see for one fit: its own fitting rows and
    the rows for the periods it must predict."""

    names: list[str]
    X: np.ndarray                 # (n_train, k)
    regimes: np.ndarray           # (n_train,)
    driver: np.ndarray            # (n_train,) the series' own driver
    system_driver: np.ndarray     # (n_train,) every active combination summed
    future_X: np.ndarray          # (h, k)
    future_regimes: np.ndarray    # (h,)
    future_driver: np.ndarray     # (h,)
    future_system_driver: np.ndarray  # (h,)

    @property
    def horizon(self) -> int:
        return len(self.future_regimes)


@dataclass
class ContextMatrix:
    """One series' context over its history AND its forecast horizon."""

    names: list[str]
    X: np.ndarray
    regimes: np.ndarray
    driver: np.ndarray
    system_driver: np.ndarray
    future_X: np.ndarray
    future_regimes: np.ndarray
    future_driver: np.ndarray
    future_system_driver: np.ndarray
    known_future: bool
    note: str = ""

    def for_fit(self, train_idx, test_idx=None) -> ContextWindow:
        """The window for one fit.

        `test_idx` is set during cross-validation, where the "future" is a
        held-out slice of history; left None for the real forecast, where the
        future comes from the driver plan.
        """
        train_idx = np.asarray(train_idx, dtype=int)
        if test_idx is None:
            fX, fr = self.future_X, self.future_regimes
            fd, fs = self.future_driver, self.future_system_driver
        else:
            test_idx = np.asarray(test_idx, dtype=int)
            fX, fr = self.X[test_idx], self.regimes[test_idx]
            fd, fs = self.driver[test_idx], self.system_driver[test_idx]
        return ContextWindow(
            names=self.names,
            X=self.X[train_idx], regimes=self.regimes[train_idx],
            driver=self.driver[train_idx],
            system_driver=self.system_driver[train_idx],
            future_X=fX, future_regimes=fr,
            future_driver=fd, future_system_driver=fs)


def _numeric(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame.columns:
        return np.full(len(frame), np.nan, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)


def _align(rows: pd.DataFrame, summary: pd.DataFrame, periods: list[str],
           columns: list[str]) -> pd.DataFrame:
    """This combination's rows for `periods`, with absent periods filled from
    the period-level conditions."""
    out = rows.reindex(periods)
    filled = summary.reindex(periods)
    absent = (out["regime_label"].isna().to_numpy()
              if "regime_label" in out.columns
              else np.ones(len(out), dtype=bool))

    for column in columns:
        default = _ABSENT.get(column, 0.0)
        if column in filled.columns:
            fallback = pd.to_numeric(filled[column], errors="coerce") \
                .to_numpy(dtype=float)
            fallback = np.where(np.isfinite(fallback), fallback, default)
        else:
            fallback = np.full(len(out), default, dtype=float)
        out[column] = np.where(absent, fallback, _numeric(out, column))

    period_regime = (filled["regime_label"].to_numpy(dtype=object)
                     if "regime_label" in filled.columns
                     else np.full(len(out), None, dtype=object))
    own_regime = (out["regime_label"].to_numpy(dtype=object)
                  if "regime_label" in out.columns
                  else np.full(len(out), None, dtype=object))
    merged = np.where(absent, period_regime, own_regime)
    out["regime_label"] = [
        IDLE_REGIME if (v is None or (isinstance(v, float) and np.isnan(v)))
        else str(v) for v in merged]
    return out


def _usable(hist: pd.DataFrame, fut: pd.DataFrame,
            names: list[str]) -> list[str]:
    """Keep only regressors that are complete over history AND horizon and
    actually vary: a column with a hole cannot forecast, and a constant column
    carries no information while making the fit singular."""
    keep = []
    for name in names:
        h = _numeric(hist, name)
        f = _numeric(fut, name) if len(fut) else np.array([], dtype=float)
        if not np.all(np.isfinite(h)) or not np.all(np.isfinite(f)):
            continue
        if len(h) > 1 and float(np.std(h)) <= 1e-12:
            continue
        keep.append(name)
    return keep


def build(context: ContextFrame | None, unit, stream, periods,
          future_periods) -> ContextMatrix | None:
    """Align one series' context rows to its observation periods.

    Returns None when context does not apply to this series at all — a
    dataset with no driver, a single unit and stream, or a combination that
    appears nowhere in the driver table. Callers treat None as "not
    applicable", never as an error (guard G5).
    """
    if context is None or context.frame.empty or not context.has_variance:
        return None
    rows = context.for_key(unit, stream)
    if rows.empty:
        return None

    periods = [str(p) for p in periods]
    future_periods = [str(p) for p in future_periods]
    summary = context.period_summary()

    # G1: a horizon period absent from the driver plan entirely means nobody
    # knows what the plant will be doing. Context models are withheld rather
    # than fed a guess.
    known_future = bool(future_periods) and bool(
        summary.index.isin(future_periods).sum() == len(future_periods))

    feature_names = [c for c in DERIVED_FEATURES if c in rows.columns]
    feature_names += [c for c in rows.columns if c.startswith(CALENDAR_PREFIX)]
    fill_columns = feature_names + ["driver_qty"]

    hist = _align(rows, summary, periods, fill_columns)
    fut = _align(rows, summary, future_periods, fill_columns) \
        if known_future else hist.iloc[:0]
    names = _usable(hist, fut, feature_names)

    def stack(frame: pd.DataFrame, n_rows: int) -> np.ndarray:
        if not names:
            return np.zeros((n_rows, 0))
        return np.column_stack([_numeric(frame, n) for n in names])

    def labels(frame: pd.DataFrame) -> np.ndarray:
        if "regime_label" not in frame.columns:
            return np.array([IDLE_REGIME] * len(frame), dtype=object)
        return frame["regime_label"].astype(str).to_numpy(dtype=object)

    return ContextMatrix(
        names=names,
        X=stack(hist, len(periods)), regimes=labels(hist),
        driver=_numeric(hist, "driver_qty"),
        system_driver=_numeric(hist, "system_driver"),
        future_X=stack(fut, len(fut)), future_regimes=labels(fut),
        future_driver=_numeric(fut, "driver_qty"),
        future_system_driver=_numeric(fut, "system_driver"),
        known_future=known_future,
        note="" if known_future else
             "the driver plan does not cover the whole forecast horizon, so "
             "the operating conditions of those periods are unknown")
