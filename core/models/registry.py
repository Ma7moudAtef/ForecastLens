"""Model registry: name → constructor + gating metadata.

The selection layer asks the registry for candidates; the registry knows how
to build each model for a given configuration. Anchors (StandardRateAnchor,
CategoryPrior) and Ensemble are constructed by the selection layer itself
because they need external context (standard rates, sibling series, fitted
members) — they are still registered for naming and metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.config import EngineConfig
from core.models.averaging import MovingAverage, WeightedMovingAverage
from core.models.base import BaseModel
from core.models.baselines import Drift, Mean, Naive, SeasonalNaive
from core.models.context_models import (
    ContextRegression,
    FixedPlusVariable,
    RegimeConditional,
)
from core.models.intermittent import SBA, TSB, Croston, ZeroForecast
from core.models.smoothing import ETS, SES, DampedHolt, Holt, HoltWinters
from core.models.statistical import ARIMA, Theta

ALL_MODEL_NAMES = [
    "Naive", "SeasonalNaive", "Drift", "Mean",
    "MovingAverage", "WeightedMovingAverage",
    "SES", "Holt", "DampedHolt", "HoltWinters", "ETS",
    "Theta", "ARIMA",
    "Croston", "SBA", "TSB",
    "StandardRateAnchor", "CategoryPrior",
    "Ensemble",
    "FixedPlusVariable", "RegimeConditional", "ContextRegression",
]

#: the models that read operating context; listed here so the UI and the
#: gate can talk about them as a group without hardcoding names elsewhere
CONTEXT_MODEL_NAMES = ["FixedPlusVariable", "RegimeConditional",
                       "ContextRegression"]


@dataclass(frozen=True)
class Candidate:
    """A concrete model instance to compete, with its lookback window
    (None = full available history)."""

    model_factory: Callable[[], BaseModel]
    name: str
    window: int | None = None

    def build(self) -> BaseModel:
        return self.model_factory()


def seasonal_capable(cfg: EngineConfig) -> set[str]:
    return {"SeasonalNaive", "HoltWinters"}


def build_nonseasonal_candidates(cfg: EngineConfig, windows: bool = True) -> list[Candidate]:
    """The 6–23 period candidate set (smooth/erratic classes)."""
    out = [
        Candidate(Naive, "Naive"),
        Candidate(Drift, "Drift"),
        Candidate(Mean, "Mean"),
        Candidate(SES, "SES"),
        Candidate(DampedHolt, "DampedHolt"),
        Candidate(Theta, "Theta"),
    ]
    window_list = cfg.models.lookback_windows if windows and not cfg.fast_mode \
        else cfg.models.lookback_windows[:1]
    for w in window_list:
        out.append(Candidate(lambda w=w: MovingAverage(w), "MovingAverage", w))
        out.append(Candidate(lambda w=w: WeightedMovingAverage(w),
                             "WeightedMovingAverage", w))
    return out


def build_seasonal_candidates(cfg: EngineConfig) -> list[Candidate]:
    """Extra candidates unlocked at >= seasonal_min_history periods."""
    m = cfg.seasonal_period
    out = [
        Candidate(lambda: SeasonalNaive(m), "SeasonalNaive"),
        Candidate(Holt, "Holt"),
        Candidate(lambda: HoltWinters(m), "HoltWinters"),
        Candidate(lambda: ETS(m, allow_seasonal=True), "ETS"),
    ]
    if cfg.models.enable_arima:
        out.append(Candidate(ARIMA, "ARIMA"))
    return out


def build_midrange_ets(cfg: EngineConfig) -> Candidate:
    """ETS restricted to non-seasonal forms (used from 15 periods up)."""
    m = cfg.seasonal_period
    return Candidate(lambda: ETS(m, allow_seasonal=False), "ETS")


def build_intermittent_candidates(cfg: EngineConfig) -> list[Candidate]:
    """Routed set for intermittent/lumpy classes — SBA is the default."""
    return [
        Candidate(SBA, "SBA"),
        Candidate(TSB, "TSB"),
        Candidate(Croston, "Croston"),
        Candidate(ZeroForecast, "ZeroForecast"),
    ]


def build_context_candidates(cfg: EngineConfig,
                             target_is_rate: bool) -> list[Candidate]:
    """The context-aware set (models 20–22).

    Offered only when the diagnostic layer found a material effect and the
    driver plan covers the whole horizon — that decision lives in the
    selection layer. Here they are ordinary candidates like any other; the
    competition does not know they are different.
    """
    c = cfg.context
    return [
        Candidate(lambda: FixedPlusVariable(target_is_rate, c.min_driver_cv),
                  "FixedPlusVariable"),
        Candidate(lambda: RegimeConditional(c.min_regime_obs),
                  "RegimeConditional"),
        Candidate(lambda: ContextRegression(c.observations_per_regressor,
                                            c.max_vif),
                  "ContextRegression"),
    ]


def filter_disabled(candidates: list[Candidate], cfg: EngineConfig) -> list[Candidate]:
    disabled = set(cfg.models.disabled_models)
    return [c for c in candidates if c.name not in disabled]
