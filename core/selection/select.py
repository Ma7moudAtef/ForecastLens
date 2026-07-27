"""Selection: run the gate, compete the candidates, pick the winner.

Ranking is on MASE only. Tie-breaks, in order: forecast stability across
folds, residual bias, fewest parameters. When models are within
~simplicity_mase_tolerance of the best MASE, the simpler one wins.
Planner overrides are respected until unlocked.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.config import EngineConfig
from core.models.anchors import CategoryPrior, StandardRateAnchor
from core.models.base import BaseModel
from core.models.baselines import Naive
from core.models.ensemble import Ensemble
from core.models.intermittent import SBA, TSB, Croston, ZeroForecast
from core.models.registry import Candidate
from core.prep.mode import Mode
from core.selection import gate as gate_mod
from core.selection.cv import CVResult, evaluate_candidate, evaluate_ensemble
from core.selection.gate import Route


@dataclass
class SeriesContext:
    """Everything selection needs about one series, mode-agnostic."""

    series_id: str
    mode: str
    pattern_class: str
    n_reliable: int
    y: np.ndarray                       # fitting target over the span
    valid: np.ndarray                   # scorable periods (reliable)
    driver: np.ndarray | None           # aligned actual driver (relative only)
    std_rate: float | None = None       # engineered standard, if any
    prior_value: float | None = None    # pooled category prior, if any
    prior_level: int | None = None
    prior_siblings: int = 0
    prior_category: str = ""
    override_model: str | None = None   # sticky planner override
    trailing_zeros: int = 0
    median_interval: float | None = None


@dataclass
class SelectionResult:
    series_id: str
    route: str
    winner_name: str
    winner_window: int | None
    winner_model: BaseModel             # fitted on full history
    mase: float | None
    reason_code: str                    # for the explanation engine
    gate_reason: str
    is_override: bool = False
    override_reason: str | None = None
    candidates: list[CVResult] = field(default_factory=list)
    validation_skipped: bool = False


def _fit_full(model: BaseModel, ctx: SeriesContext) -> BaseModel:
    return model.fit(ctx.y, driver=ctx.driver)


def _cold_start(ctx: SeriesContext) -> tuple[BaseModel, str]:
    """The cold-start ladder. Relative: standard-rate anchor → category prior
    → naive. Absolute: category prior → naive. A Relative series with too
    little driver history stays Relative and lands here — it never flips."""
    if ctx.mode == Mode.RELATIVE.value and ctx.std_rate is not None:
        return StandardRateAnchor(ctx.std_rate), "cold_start_standard_rate"
    if ctx.prior_value is not None:
        return CategoryPrior(ctx.prior_value, ctx.prior_level or 0,
                             ctx.prior_siblings, ctx.prior_category), \
            "cold_start_category_prior"
    if len(ctx.y) >= 1 and np.any(ctx.y != 0):
        return Naive(), "cold_start_naive"
    return ZeroForecast(), "cold_start_zero"


def _route_intermittent(ctx: SeriesContext) -> tuple[BaseModel, str]:
    """Deterministic routing inside the Croston family — no competition.
    SBA is the default (bias-corrected); TSB when the series shows an
    obsolescence signal (long trailing silence); ZeroForecast when nothing
    has moved at all."""
    if not np.any(ctx.y > 0):
        return ZeroForecast(), "routed_zero"
    median_iv = ctx.median_interval or 1.0
    if ctx.trailing_zeros >= max(4.0, 2.0 * median_iv):
        return TSB(), "routed_tsb_obsolescence"
    return SBA(), "routed_sba"


def _rank_key(r: CVResult) -> tuple:
    return (r.mase if r.mase is not None else math.inf,)


def _tie_break(pool: list[CVResult]) -> CVResult:
    """Within the simplicity tolerance: stability, then |bias|, then fewest
    parameters, then name for determinism."""
    return min(pool, key=lambda r: (
        round(r.stability, 6) if r.stability is not None else math.inf,
        round(abs(r.bias), 9) if r.bias is not None else math.inf,
        r.n_params,
        r.name))


def _build_from_result(r: CVResult, candidates: dict[tuple, Candidate],
                       ok_results: list[CVResult], ctx: SeriesContext) -> BaseModel:
    if r.name == "Ensemble":
        member_results = [m for m in ok_results
                          if m is not r and (m.name, m.window) in candidates][:3]
        members = [
            _fit_full(candidates[(m.name, m.window)].build(), ctx)
            for m in sorted(member_results, key=_rank_key)[:3]]
        return Ensemble(members)
    return _fit_full(candidates[(r.name, r.window)].build(), ctx)


def select_for_series(ctx: SeriesContext, cfg: EngineConfig) -> SelectionResult:
    decision = gate_mod.decide(ctx.n_reliable, ctx.pattern_class, ctx.mode, cfg)

    # --- routed intermittent: no competition -------------------------------
    if decision.route is Route.ROUTED_INTERMITTENT:
        model, code = _route_intermittent(ctx)
        _fit_full(model, ctx)
        result = SelectionResult(
            series_id=ctx.series_id, route=decision.route.value,
            winner_name=model.name, winner_window=None, winner_model=model,
            mase=None, reason_code=code, gate_reason=decision.reason,
            validation_skipped=True)
        return _apply_override(result, ctx, cfg)

    # --- cold start: ladder, no competition --------------------------------
    if decision.route is Route.COLD_START:
        model, code = _cold_start(ctx)
        _fit_full(model, ctx)
        result = SelectionResult(
            series_id=ctx.series_id, route=decision.route.value,
            winner_name=model.name, winner_window=None, winner_model=model,
            mase=None, reason_code=code, gate_reason=decision.reason,
            validation_skipped=True)
        return _apply_override(result, ctx, cfg)

    # --- competition --------------------------------------------------------
    candidates: dict[tuple, Candidate] = {
        (c.name, c.window): c for c in decision.candidates}
    # the standard-rate anchor always competes for Relative series
    if ctx.mode == Mode.RELATIVE.value and ctx.std_rate is not None:
        anchor = Candidate(
            lambda sr=ctx.std_rate: StandardRateAnchor(sr), "StandardRateAnchor")
        candidates[(anchor.name, None)] = anchor

    results: list[CVResult] = []
    for cand in candidates.values():
        results.append(evaluate_candidate(cand, ctx.y, ctx.driver, cfg,
                                          valid=ctx.valid))
    ok = [r for r in results if r.status == "ok" and r.mase is not None
          and np.isfinite(r.mase)]

    if not ok:
        # every candidate failed or was skipped → honest fallback
        model, code = _cold_start(ctx)
        _fit_full(model, ctx)
        result = SelectionResult(
            series_id=ctx.series_id, route="compete_fallback",
            winner_name=model.name, winner_window=None, winner_model=model,
            mase=None, reason_code=code, gate_reason=decision.reason,
            candidates=results, validation_skipped=True)
        return _apply_override(result, ctx, cfg)

    ok.sort(key=_rank_key)

    # ensemble: offered only when the top models are within ~10% MASE
    top = ok[:3]
    if len(top) >= 2 and top[0].mase and top[0].mase > 0:
        spread = (top[-1].mase - top[0].mase) / top[0].mase
        if spread <= cfg.models.ensemble_mase_tolerance:
            ens = evaluate_ensemble(top, ctx.y, cfg, valid=ctx.valid)
            if ens is not None:
                ok.append(ens)
                results.append(ens)
                ok.sort(key=_rank_key)

    best = ok[0]
    tol = cfg.selection.simplicity_mase_tolerance
    threshold = best.mase * (1.0 + tol) if best.mase > 0 else tol
    pool = [r for r in ok if r.mase <= threshold]
    winner_res = _tie_break(pool)

    winner_model = _build_from_result(winner_res, candidates, ok, ctx)
    result = SelectionResult(
        series_id=ctx.series_id, route=Route.COMPETE.value,
        winner_name=winner_res.name, winner_window=winner_res.window,
        winner_model=winner_model, mase=winner_res.mase,
        reason_code="competition_winner", gate_reason=decision.reason,
        candidates=results)
    return _apply_override(result, ctx, cfg)


def _apply_override(result: SelectionResult, ctx: SeriesContext,
                    cfg: EngineConfig) -> SelectionResult:
    """A locked planner override replaces the auto winner but keeps the
    competition table intact for comparison."""
    if not ctx.override_model or ctx.override_model == result.winner_name:
        return result
    model = _instantiate_by_name(ctx.override_model, cfg, ctx)
    if model is None:
        result.override_reason = (
            f"override '{ctx.override_model}' could not be applied "
            "(model unavailable for this series); automatic winner kept")
        return result
    try:
        _fit_full(model, ctx)
    except Exception as exc:
        result.override_reason = (
            f"override '{ctx.override_model}' failed to fit "
            f"({type(exc).__name__}); automatic winner kept")
        return result
    override_mase = next(
        (r.mase for r in result.candidates
         if r.name == ctx.override_model and r.status == "ok"), None)
    result.winner_name = model.name
    result.winner_window = None
    result.winner_model = model
    result.mase = override_mase
    result.is_override = True
    result.reason_code = "planner_override"
    return result


def _instantiate_by_name(name: str, cfg: EngineConfig,
                         ctx: SeriesContext) -> BaseModel | None:
    from core.models.averaging import MovingAverage, WeightedMovingAverage
    from core.models.baselines import Drift, Mean, SeasonalNaive
    from core.models.smoothing import ETS, SES, DampedHolt, Holt, HoltWinters
    from core.models.statistical import ARIMA, Theta

    m = cfg.seasonal_period
    w = cfg.models.lookback_windows[0]
    simple: dict[str, BaseModel] = {
        "Naive": Naive(), "Drift": Drift(), "Mean": Mean(),
        "SES": SES(), "Holt": Holt(), "DampedHolt": DampedHolt(),
        "Theta": Theta(), "ARIMA": ARIMA(),
        "Croston": Croston(), "SBA": SBA(), "TSB": TSB(),
        "ZeroForecast": ZeroForecast(),
        "SeasonalNaive": SeasonalNaive(m), "HoltWinters": HoltWinters(m),
        "ETS": ETS(m, allow_seasonal=len(ctx.y) >= 2 * m),
        "MovingAverage": MovingAverage(w),
        "WeightedMovingAverage": WeightedMovingAverage(w),
    }
    if name == "StandardRateAnchor" and ctx.std_rate is not None:
        return StandardRateAnchor(ctx.std_rate)
    if name == "CategoryPrior" and ctx.prior_value is not None:
        return CategoryPrior(ctx.prior_value, ctx.prior_level or 0,
                             ctx.prior_siblings, ctx.prior_category)
    return simple.get(name)


_VALIDATION_COLUMNS = ["run_id", "series_id", "model_name", "window", "mase",
                       "mae", "rmse", "mape", "smape", "n_origins",
                       "fit_seconds", "status", "fail_reason"]


def results_to_frame(run_id: str, sel: SelectionResult) -> pd.DataFrame:
    """Flatten candidate CV results for the validation_result table. Always
    returns the full column set, even with zero candidates (routed and
    cold-start series skip the competition entirely)."""
    rows = []
    for r in sel.candidates:
        rows.append({
            "run_id": run_id, "series_id": sel.series_id,
            "model_name": r.name, "window": r.window,
            "mase": None if r.mase is None or not np.isfinite(r.mase) else r.mase,
            "mae": r.mae, "rmse": r.rmse, "mape": r.mape, "smape": r.smape,
            "n_origins": r.n_origins, "fit_seconds": r.fit_seconds,
            "status": r.status, "fail_reason": r.fail_reason,
        })
    return pd.DataFrame(rows, columns=_VALIDATION_COLUMNS)
