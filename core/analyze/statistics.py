"""Per-series behaviour analysis.

Enriches the series table with descriptive statistics, trend and seasonality
strength, stationarity, autocorrelation, outlier and missing percentages,
structural breaks, ADI/CV² and the pattern class. Every computation is
wrapped so a single odd series can never abort the run.
"""
from __future__ import annotations

import warnings as _pywarnings

import numpy as np
import pandas as pd

from core.analyze.classify import classify
from core.config import EngineConfig
from core.prep.series_builder import PreparedData


def _trend_seasonal_strength(y: np.ndarray, m: int) -> tuple[float | None, float | None]:
    """STL-based strengths when two full cycles exist; OLS-R² trend otherwise."""
    try:
        if len(y) >= 2 * m + 1 and np.ptp(y) > 0:
            from statsmodels.tsa.seasonal import STL
            res = STL(pd.Series(y), period=m, robust=True).fit()
            resid_var = np.var(res.resid)
            deseason = res.trend + res.resid
            detrend = res.seasonal + res.resid
            trend = max(0.0, 1.0 - resid_var / np.var(deseason)) if np.var(deseason) > 0 else 0.0
            seasonal = max(0.0, 1.0 - resid_var / np.var(detrend)) if np.var(detrend) > 0 else 0.0
            return float(trend), float(seasonal)
        if len(y) >= 4 and np.ptp(y) > 0:
            t = np.arange(len(y), dtype=float)
            r = np.corrcoef(t, y)[0, 1]
            return float(0.0 if np.isnan(r) else r * r), None
    except Exception:
        pass
    return None, None


def _stationary(y: np.ndarray) -> bool | None:
    try:
        if len(y) < 8 or np.ptp(y) == 0:
            return None
        from statsmodels.tsa.stattools import adfuller
        with _pywarnings.catch_warnings():
            _pywarnings.simplefilter("ignore")
            p = adfuller(y, autolag="AIC")[1]
        return bool(p < 0.05)
    except Exception:
        return None


def _autocorr_lag1(y: np.ndarray) -> float | None:
    if len(y) < 3 or np.std(y) == 0:
        return None
    a, b = y[:-1], y[1:]
    denom = np.std(a) * np.std(b)
    if denom == 0:
        return None
    return float(np.mean((a - a.mean()) * (b - b.mean())) / denom)


def _outlier_pct(y: np.ndarray) -> float:
    nz = y[y > 0]
    if len(nz) < 4:
        return 0.0
    med = np.median(nz)
    mad = np.median(np.abs(nz - med))
    if mad == 0:
        return 0.0
    z = 0.6745 * np.abs(nz - med) / mad
    return float((z > 3.5).mean())


def _structural_break(y: np.ndarray, periods: list[str],
                      min_segment: int = 4, threshold: float = 2.0) -> str | None:
    """Largest mean shift between two segments, flagged when the shift exceeds
    `threshold` pooled standard deviations. Deliberately simple and explainable."""
    n = len(y)
    if n < 2 * min_segment:
        return None
    best_stat, best_idx = 0.0, None
    for i in range(min_segment, n - min_segment + 1):
        a, b = y[:i], y[i:]
        pooled = np.sqrt((np.var(a) * len(a) + np.var(b) * len(b)) / n)
        if pooled == 0:
            continue
        stat = abs(a.mean() - b.mean()) / pooled
        if stat > best_stat:
            best_stat, best_idx = stat, i
    if best_idx is not None and best_stat > threshold:
        return periods[best_idx]
    return None


def _forecastability(pattern_class: str, cv: float | None, n_reliable: int,
                     seasonal_min: int) -> float:
    base = {
        "smooth": 0.9, "erratic": 0.55, "intermittent": 0.5,
        "lumpy": 0.3, "too_short": 0.2,
    }.get(pattern_class, 0.5)
    history_factor = min(1.0, n_reliable / seasonal_min) if seasonal_min else 1.0
    noise_penalty = 0.0
    if cv is not None:
        noise_penalty = min(0.3, 0.15 * max(0.0, cv - 0.5))
    return float(np.clip(base * (0.5 + 0.5 * history_factor) - noise_penalty, 0.0, 1.0))


def _data_quality(missing_pct: float, unreliable_pct: float,
                  outlier_pct: float) -> float:
    return float(np.clip(
        1.0 - 0.4 * missing_pct - 0.4 * unreliable_pct - 0.2 * outlier_pct,
        0.0, 1.0))


def analyze_all(prep: PreparedData, cfg: EngineConfig) -> pd.DataFrame:
    """Return the series table enriched with behaviour columns."""
    m = cfg.seasonal_period
    obs = prep.observations
    rows = []
    for sid, g in obs.groupby("series_id", sort=False):
        g = g.sort_values("period")
        span = g["target"].to_numpy(dtype=float)
        span = np.nan_to_num(span, nan=0.0)
        observed = g.loc[g["is_gap_filled"] == 0, "target"].dropna().to_numpy(dtype=float)
        reliable = g.loc[(g["is_gap_filled"] == 0) & (g["is_reliable"] == 1),
                         "target"].dropna().to_numpy(dtype=float)

        cls, adi, cv2 = classify(span, min_len=cfg.gate.min_history_competition)

        desc_src = observed if len(observed) else np.array([0.0])
        mean = float(desc_src.mean())
        std = float(desc_src.std(ddof=0))
        cv = float(std / mean) if mean > 0 else None

        trend, seasonal = _trend_seasonal_strength(span, m)
        missing_pct = float((g["is_gap_filled"] == 1).mean())
        unreliable_pct = float((g["is_reliable"] == 0).mean())
        outlier_pct = _outlier_pct(desc_src)

        rows.append({
            "series_id": sid,
            "target_mean": mean,
            "target_median": float(np.median(desc_src)),
            "target_min": float(desc_src.min()),
            "target_max": float(desc_src.max()),
            "target_std": std,
            "target_cv": cv,
            "trend_strength": trend,
            "seasonality_strength": seasonal,
            "stationary": _stationary(observed),
            "autocorr_lag1": _autocorr_lag1(observed),
            "outlier_pct": outlier_pct,
            "missing_pct": missing_pct,
            "unreliable_pct": unreliable_pct,
            "structural_break_period": _structural_break(
                span, g["period"].tolist()),
            "pattern_class": cls.value,
            "adi": adi,
            "cv2": cv2,
            "forecastability": _forecastability(
                cls.value, cv, len(reliable), cfg.gate.seasonal_min_history),
            "data_quality": _data_quality(missing_pct, unreliable_pct, outlier_pct),
        })
    stats = pd.DataFrame(rows)
    return prep.series.merge(stats, on="series_id", how="left")
