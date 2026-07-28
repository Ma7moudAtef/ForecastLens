"""Rolling-origin cross-validation. Chronological only — never a random split.

The leakage guard is a LIVE assertion kept in production code, not only in
tests: every fold asserts max(train index) < min(test index).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from core.config import EngineConfig
from core.models.registry import Candidate
from core.selection import metrics as M


@dataclass
class CVResult:
    name: str
    window: int | None
    status: str = "ok"                # ok | failed | skipped
    fail_reason: str | None = None
    n_origins: int = 0
    mase: float | None = None
    mae: float | None = None
    rmse: float | None = None
    mape: float | None = None
    smape: float | None = None
    stability: float | None = None    # std of fold MASE — tie-break 1
    bias: float | None = None         # mean signed error — tie-break 2
    n_params: int = 0
    fit_seconds: float = 0.0
    #: origin -> predicted values for that fold (test positions), for ensemble
    fold_predictions: dict[int, np.ndarray] = field(default_factory=dict)
    fold_mases: list[float] = field(default_factory=list)


def fold_origins(n: int, horizon: int, min_train: int, max_origins: int) -> list[int]:
    """Origins for a series of length n. The LAST `max_origins` origins are
    kept — recent folds are the most representative of current behaviour."""
    origins = list(range(min_train, n - horizon + 1))
    return origins[-max_origins:]


def _score_folds(result: CVResult, y: np.ndarray, valid: np.ndarray) -> None:
    maes, rmses, mapes, smapes, mases, biases = [], [], [], [], [], []
    for origin, preds in sorted(result.fold_predictions.items()):
        test_idx = np.arange(origin, origin + len(preds))
        mask = valid[test_idx]
        if not mask.any():
            continue
        actual = y[test_idx][mask]
        fc = preds[mask]
        train = y[:origin]
        maes.append(M.mae(actual, fc))
        rmses.append(M.rmse(actual, fc))
        mp = M.mape(actual, fc)
        if mp is not None:
            mapes.append(mp)
        sp = M.smape(actual, fc)
        if sp is not None:
            smapes.append(sp)
        mases.append(M.mase(actual, fc, train))
        biases.append(float(np.mean(fc - actual)))
    if not mases:
        result.status = "failed"
        result.fail_reason = "no scorable test periods in any fold"
        return
    result.fold_mases = mases
    finite = [m for m in mases if np.isfinite(m)]
    result.mase = float(np.mean(mases)) if finite == mases else float("inf")
    result.mae = float(np.mean(maes))
    result.rmse = float(np.mean(rmses))
    result.mape = float(np.mean(mapes)) if mapes else None
    result.smape = float(np.mean(smapes)) if smapes else None
    result.stability = float(np.std(mases)) if finite == mases else float("inf")
    result.bias = float(np.mean(biases))
    result.n_origins = len(mases)


def evaluate_candidate(cand: Candidate, y: np.ndarray,
                       driver: np.ndarray | None, cfg: EngineConfig,
                       valid: np.ndarray | None = None,
                       context=None) -> CVResult:
    """Rolling-origin evaluation of one candidate on one series.

    ``valid`` marks periods that may be SCORED against (reliable periods);
    unreliable test points are excluded from the metrics. Returns status
    'skipped' when fewer than min_cv_origins folds are possible — the caller
    must then use the gate's default rather than fabricate a competition on
    too few folds.

    ``context`` is the series' operating conditions. Models that declare
    ``uses_context`` are handed the fold's own slice of it — the training
    rows and the rows of the periods they are about to predict. Those future
    rows come from the driver plan, which is known in advance, so this is not
    leakage; the fold boundary below is asserted exactly as for every other
    model.
    """
    horizon = cfg.cv.horizon
    n = len(y)
    if valid is None:
        valid = np.ones(n, dtype=bool)
    probe = cand.build()
    min_train = max(probe.min_history, 2)
    origins = fold_origins(n, horizon, min_train, cfg.cv.max_origins)
    result = CVResult(name=cand.name, window=cand.window, n_params=probe.n_params)
    if len(origins) < cfg.gate.min_cv_origins:
        result.status = "skipped"
        result.fail_reason = (
            f"only {len(origins)} validation origin(s) possible; "
            f"at least {cfg.gate.min_cv_origins} required")
        return result

    start = time.perf_counter()
    for origin in origins:
        train_idx = np.arange(0, origin)
        test_idx = np.arange(origin, min(origin + horizon, n))
        # Trap 3 — the leakage guard. Live in production, always.
        assert train_idx.max() < test_idx.min(), "CV leakage: train overlaps test"
        try:
            model = cand.build()
            if context is not None and getattr(model, "uses_context", False):
                model.set_context(context.for_fit(train_idx, test_idx))
            model.fit(y[train_idx],
                      driver=None if driver is None else driver[train_idx])
            preds = np.asarray(model.predict(len(test_idx)), dtype=float)
        except Exception as exc:  # a failed fit disqualifies, never aborts
            result.status = "failed"
            result.fail_reason = f"{type(exc).__name__}: {exc}"
            return result
        if not np.all(np.isfinite(preds)):
            result.status = "failed"
            result.fail_reason = "non-finite predictions"
            return result
        result.fold_predictions[origin] = preds
    result.fit_seconds = time.perf_counter() - start
    _score_folds(result, y, valid)
    return result


def evaluate_ensemble(members: list[CVResult], y: np.ndarray,
                      cfg: EngineConfig,
                      valid: np.ndarray | None = None) -> CVResult | None:
    """Score an ensemble by averaging the members' already-computed fold
    predictions over their COMMON origins — same folds, no refitting."""
    common = set.intersection(*(set(m.fold_predictions) for m in members))
    if len(common) < cfg.gate.min_cv_origins:
        return None
    result = CVResult(
        name="Ensemble", window=None,
        n_params=sum(m.n_params for m in members))
    for origin in sorted(common):
        preds = np.mean([m.fold_predictions[origin] for m in members], axis=0)
        result.fold_predictions[origin] = preds
    if valid is None:
        valid = np.ones(len(y), dtype=bool)
    _score_folds(result, y, valid)
    if result.status != "ok":
        return None
    return result
