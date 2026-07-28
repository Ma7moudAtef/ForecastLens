"""run_forecast(): the headless batch orchestrator.

Load → validate → prepare → analyze → select (parallel across series) →
generate → reconstruct → persist to SQLite. The UI only ever reads what this
writes. One series failing must never abort the run (N7): per-series work is
wrapped, failures are recorded as warnings with an explicit reason.
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from core.config import AppConfig, EngineConfig
from core.forecast.generate import confidence_label, confidence_score, generate
from core.forecast.reconstruct import plan_lookup, reconstruct
from core.io.excel_source import ExcelSource
from core.log import get_logger
from core.paths import is_frozen
from core.prep.calendar import full_range, parse_period
from core.prep.mode import Mode
from core.prep.series_builder import PreparedData, build_series
from core.selection.select import (
    SelectionResult,
    SeriesContext,
    results_to_frame,
    select_for_series,
)
from core.store.repository import Repository
from core.validate import rules
from core.analyze.statistics import analyze_all

log = get_logger("pipeline")

ProgressCb = Callable[[str, float], None]
LogCb = Callable[[str], None]
CancelCb = Callable[[], bool]

#: series handled per parallel chunk — the granularity at which progress is
#: reported and a cancellation request is honoured
CHUNK_SIZE = 40


class RunCancelled(Exception):
    """Raised when the caller asked for the run to stop. Partial results are
    discarded so a half-finished forecast can never be mistaken for a real
    one."""


def _noop_progress(stage: str, fraction: float) -> None:
    pass


def _noop_log(message: str) -> None:
    pass


def _never_cancel() -> bool:
    return False


# --- operating context --------------------------------------------------------

def series_context(context_frame, row, periods: list[str],
                   target: np.ndarray, usable: np.ndarray,
                   cfg: EngineConfig):
    """One series' operating conditions: the aligned matrix a context model
    could fit on, and the diagnosis EVERY series gets whether or not any
    model ends up using it.

    Returns (matrix | None, ContextDiagnosis). A None matrix is not an error —
    it means this dataset has no operating variation to learn from, which is
    the ordinary case for a single-line plant (guard G5).
    """
    from core.context import diagnose as ctx_diagnose
    from core.context import matrix as ctx_matrix

    if not cfg.context.enabled:
        return None, ctx_diagnose.ContextDiagnosis(
            skip_reason="context-aware forecasting is switched off",
            verdict="Operating context was not examined: the feature is "
                    "switched off for this run.")
    if context_frame is None:
        return None, ctx_diagnose.ContextDiagnosis(
            skip_reason="no operating context in this dataset",
            verdict="This dataset carries no driver activity to read "
                    "operating conditions from.")
    if not context_frame.has_variance:
        return None, ctx_diagnose.ContextDiagnosis(
            skip_reason=context_frame.note or "no operating variation",
            verdict=(context_frame.note or "Operating conditions never "
                     "change").capitalize() + ".")

    last = parse_period(row.last_period, cfg.granularity)
    future = [str(p) for p in
              full_range(last + 1, last + cfg.forecast.horizon)]
    matrix = ctx_matrix.build(context_frame, row.line, row.output_type,
                              periods, future)
    if matrix is None:
        return None, ctx_diagnose.ContextDiagnosis(
            skip_reason="this line and output appear in no driver record",
            verdict="No driver activity is recorded for this line and "
                    "output, so its operating conditions are unknown.")
    diag = ctx_diagnose.diagnose(target, matrix.regimes, cfg, valid=usable)
    if diag.material and not matrix.known_future:
        # the effect is real but nobody has planned the horizon: say so
        # instead of quietly dropping the models (G5 degrades, it does not
        # hide)
        diag.material = False
        diag.verdict += (" Context models were still not offered because "
                         + matrix.note + ".")
    return matrix, diag


# --- context assembly ---------------------------------------------------------

def _interpolate_unreliable(target: np.ndarray, reliable: np.ndarray) -> np.ndarray:
    """Fitting vector: unreliable values are excluded by replacing them with a
    linear interpolation of reliable neighbours (keeps seasonal phase intact).
    Series with no reliable periods at all return zeros — they never reach a
    fitted model anyway (cold-start ladder)."""
    if reliable.all():
        return target
    s = pd.Series(np.where(reliable, target, np.nan))
    s = s.interpolate(method="linear", limit_direction="both")
    return s.fillna(0.0).to_numpy(dtype=float)


def _trailing_zeros(y: np.ndarray) -> int:
    nz = np.flatnonzero(y > 0)
    return len(y) if len(nz) == 0 else len(y) - 1 - int(nz[-1])


def _median_interval(y: np.ndarray) -> float | None:
    nz = np.flatnonzero(y > 0)
    if len(nz) < 2:
        return None
    return float(np.median(np.diff(nz)))


def build_category_priors(analyzed: pd.DataFrame, items: pd.DataFrame,
                          cfg: EngineConfig) -> dict:
    """Pooled target levels per (mode, category level, category value), from
    series with enough usable history. Returns
    {(mode, level, value): (pooled_mean, n_items)}."""
    eligible = analyzed[analyzed["n_reliable"] >= cfg.gate.min_history_competition]
    merged = eligible.merge(
        items[["item_code", "cat_l1", "cat_l2", "cat_l3"]],
        on="item_code", how="inner")
    pools: dict = {}
    for level, col in ((3, "cat_l3"), (2, "cat_l2"), (1, "cat_l1")):
        grp = merged.dropna(subset=[col]).groupby(["mode", col])
        for (mode, value), g in grp:
            pools[(mode, level, value)] = (
                float(g["target_mean"].mean()),
                int(g["item_code"].nunique()))
    return pools


def _prior_for(item_code: str, mode: str, items_idx: dict, pools: dict):
    cats = items_idx.get(item_code)
    if not cats:
        return None, None, 0, ""
    for level, value in ((3, cats.get("cat_l3")), (2, cats.get("cat_l2")),
                         (1, cats.get("cat_l1"))):
        if value is None or (isinstance(value, float) and np.isnan(value)):
            continue
        pooled = pools.get((mode, level, value))
        if pooled and pooled[1] >= 1:
            return pooled[0], level, pooled[1], str(value)
    return None, None, 0, ""


def build_contexts(prep: PreparedData, analyzed: pd.DataFrame,
                   raw_items: pd.DataFrame, standard_rates: pd.DataFrame,
                   model_overrides: dict[str, str],
                   cfg: EngineConfig,
                   context_frame=None) -> list[SeriesContext]:
    std_lookup = {
        (r.item_code, r.line, r.output_type): float(r.std_rate)
        for r in standard_rates.itertuples() if pd.notna(r.std_rate)}
    items_idx = (
        raw_items.drop_duplicates("item_code")
        .set_index("item_code")[["cat_l1", "cat_l2", "cat_l3"]]
        .to_dict("index"))
    pools = build_category_priors(analyzed, raw_items.drop_duplicates("item_code"), cfg)

    contexts = []
    obs_by_series = dict(tuple(prep.observations.groupby("series_id", sort=False)))
    for row in analyzed.itertuples():
        g = obs_by_series[row.series_id].sort_values("period")
        target = np.nan_to_num(g["target"].to_numpy(dtype=float), nan=0.0)
        reliable = g["is_reliable"].to_numpy(dtype=bool)
        y_fit = _interpolate_unreliable(target, reliable)
        # periods that may actually be used: reliable, and belonging to a
        # period where this line ran at all
        usable = reliable.copy()
        if "is_applicable" in g.columns:
            usable &= g["is_applicable"].to_numpy(dtype=bool)
        driver = None
        if row.mode == Mode.RELATIVE.value:
            # The driver is the weight in every driver-weighted average
            # (Mean, MovingAverage, WeightedMovingAverage). Periods excluded
            # from fitting must carry no weight: their target was filled in
            # by interpolation, so letting the real driver vote for a
            # synthetic value would bias the average.
            driver = np.where(usable, g["driver_qty"].to_numpy(dtype=float),
                              np.nan)
        prior_value, prior_level, prior_siblings, prior_cat = _prior_for(
            row.item_code, row.mode, items_idx, pools)
        matrix, diagnosis = series_context(
            context_frame, row, g["period"].astype(str).tolist(),
            target, usable, cfg)
        contexts.append(SeriesContext(
            series_id=row.series_id,
            mode=row.mode,
            pattern_class=row.pattern_class,
            n_reliable=int(row.n_reliable),
            y=y_fit,
            valid=reliable,
            driver=driver,
            std_rate=std_lookup.get((row.item_code, row.line, row.output_type)),
            prior_value=prior_value,
            prior_level=prior_level,
            prior_siblings=prior_siblings,
            prior_category=prior_cat,
            override_model=model_overrides.get(row.series_id),
            trailing_zeros=_trailing_zeros(target),
            median_interval=_median_interval(target),
            context=matrix,
            diagnosis=diagnosis,
        ))
    return contexts


# --- per-series worker --------------------------------------------------------

def _process_series(ctx: SeriesContext, meta: dict, cfg: EngineConfig,
                    plan: dict[tuple, float]) -> dict:
    """Select, generate, reconstruct and explain one series. Returns plain
    picklable frames. Any exception is captured, not raised."""
    from core.explain import engine as explain

    try:
        sel = select_for_series(ctx, cfg)
        last_period = parse_period(meta["last_period"], cfg.granularity)
        conf = confidence_score(
            sel.mase, ctx.n_reliable, meta.get("forecastability") or 0.0,
            meta.get("data_quality") or 0.0, cfg, sel.validation_skipped)
        fc = generate(sel.winner_model, last_period, cfg, conf)
        fc = reconstruct(fc, ctx.mode, meta["line"], meta["output_type"],
                         plan, cfg)
        fc.insert(0, "series_id", ctx.series_id)

        winner_res = next(
            (r for r in sel.candidates
             if r.name == sel.winner_name and r.window == sel.winner_window
             and r.status == "ok"), None)
        selection = {
            "series_id": ctx.series_id,
            "model_name": sel.winner_name,
            "window": sel.winner_window,
            "mase": sel.mase,
            "n_origins": winner_res.n_origins if winner_res else 0,
            "confidence": conf,
            "confidence_label": confidence_label(conf),
            "is_override": int(sel.is_override),
            "override_reason": sel.override_reason,
            "route": sel.route,
            "reason_code": sel.reason_code,
            "gate_reason": sel.gate_reason,
            "winner_explain": sel.winner_model.explain(),
        }
        selection["reason_text"] = explain.selection_reason(selection, meta)

        validation = results_to_frame("", sel)
        rejected = []
        for r in sel.candidates:
            if r.name == sel.winner_name and r.window == sel.winner_window:
                continue
            cand = {"model_name": r.name, "window": r.window,
                    "mase": r.mase, "status": r.status,
                    "fail_reason": r.fail_reason}
            cand["reason"] = explain.rejection_reason(
                cand, {"mase": sel.mase}, meta)
            rejected.append(cand)
        selection["rejected"] = rejected

        caveats: list[tuple[str, str]] = []
        if meta.get("is_orphan"):
            caveats.append(("ORPHAN_RECONSTRUCTION", explain.orphan_caveat(
                meta["line"], meta["output_type"])))
        if meta.get("mode_source") in ("declared_bom", "declared_ui"):
            caveats.append(("DECLARED_MODE", explain.declared_mode_note(
                ctx.mode, meta["mode_source"])))
        if ctx.driver is not None and sel.winner_name in explain.SMOOTHING_FAMILY:
            d = ctx.driver[ctx.valid]
            d = d[np.isfinite(d)]
            if len(d) >= 4 and d.mean() > 0:
                driver_cv = float(d.std() / d.mean())
                if driver_cv > 0.5:
                    caveats.append(("SMOOTHING_BIAS_RISK",
                                    explain.smoothing_bias_caveat(driver_cv)))
        if sel.reason_code == "routed_tsb_obsolescence":
            caveats.append(("OBSOLESCENCE_SIGNAL", explain.obsolescence_note()))

        return {"series_id": ctx.series_id, "status": "ok",
                "selection": selection, "validation": validation,
                "forecast": fc, "caveats": caveats}
    except Exception as exc:
        log.exception("series %s failed", ctx.series_id)
        return {"series_id": ctx.series_id, "status": "failed",
                "error": f"{type(exc).__name__}: {exc}"}


# --- the orchestrator ---------------------------------------------------------

def run_forecast(input_path: str | Path, cfg: EngineConfig | None = None,
                 db_path: str | Path | None = None,
                 progress_cb: ProgressCb | None = None,
                 run_name: str | None = None,
                 log_cb: LogCb | None = None,
                 cancel_cb: CancelCb | None = None) -> str:
    """Execute a full batch run and persist everything. Returns run_id.

    ``log_cb`` receives verbose, human-readable progress lines. ``cancel_cb``
    is polled between stages and between series chunks; when it returns True
    the run stops, its partial results are removed, and RunCancelled is
    raised.
    """
    cfg = cfg or EngineConfig()
    progress = progress_cb or _noop_progress
    emit = log_cb or _noop_log
    cancelled = cancel_cb or _never_cancel
    db_path = db_path or AppConfig().db_path
    started = time.perf_counter()

    def checkpoint(run_id: str | None = None) -> None:
        if cancelled():
            raise RunCancelled(run_id or "")

    with Repository(db_path) as repo:
        emit(f"Reading workbook: {Path(input_path).name}")
        progress("loading workbook", 0.02)
        raw = ExcelSource(input_path).load()
        input_hash = hashlib.sha256(Path(input_path).read_bytes()).hexdigest()[:16]
        emit(f"Loaded {len(raw.consumption):,} consumption rows, "
             f"{raw.consumption['item_code'].nunique()} items, "
             f"{len(raw.driver):,} driver rows")
        checkpoint()

        progress("validating", 0.06)
        emit("Validating the data…")
        warnings = rules.run_all(raw, cfg)
        if rules.has_fatal(warnings):
            fatal = [w.message for w in warnings if w.severity == rules.Severity.FATAL]
            raise RuntimeError("fatal validation errors: " + "; ".join(fatal))
        by_severity = {}
        for w in warnings:
            by_severity[w.severity.value] = by_severity.get(w.severity.value, 0) + 1
        emit("Validation finished: " + (", ".join(
            f"{n} {sev}" for sev, n in sorted(by_severity.items()))
            or "no issues"))
        checkpoint()

        progress("building series", 0.12)
        emit("Building the forecast series (gap filling, calendar "
             "normalization, driver join)…")
        mode_overrides = {
            r.item_code: r.mode for r in repo.get_mode_overrides().itertuples()}
        prep = build_series(raw, cfg, mode_overrides=mode_overrides)
        warnings = warnings + prep.warnings
        n_relative = int((prep.series["mode"] == "relative").sum())
        emit(f"Built {len(prep.series)} series — {n_relative} relative "
             f"(rate-based), {len(prep.series) - n_relative} absolute "
             f"(quantity-based)")
        if mode_overrides:
            emit(f"Applied {len(mode_overrides)} planner mode declaration(s)")
        checkpoint()

        progress("analyzing behaviour", 0.20)
        emit("Studying each series: trend, seasonality, volatility, demand "
             "pattern…")
        analyzed = analyze_all(prep, cfg)
        classes = analyzed["pattern_class"].value_counts().to_dict()
        emit("Demand patterns: " + ", ".join(
            f"{n} {name}" for name, n in sorted(classes.items())))
        checkpoint()

        run_id = repo.create_run(cfg.model_dump_json(), source_name=raw.source_name,
                                 input_hash=input_hash, name=run_name,
                                 scope_note=cfg.scope.note())

        context_frame = None
        if cfg.context.enabled:
            from core.context import features as ctx_features

            context_frame = ctx_features.derive(
                prep.driver_agg, cfg, calendar=getattr(raw, "context_calendar",
                                                       None))
            if context_frame.has_variance:
                emit(f"Operating context: {len(context_frame.regime_counts)} "
                     "distinct condition(s) seen in the driver history"
                     + (f", plus {len(context_frame.calendar_features)} "
                        "planner-supplied factor(s)"
                        if context_frame.calendar_features else ""))
            else:
                emit("Operating context: " + (context_frame.note
                                              or "nothing to learn from"))

        model_overrides = {
            r.series_id: r.model_name
            for r in repo.get_model_overrides().itertuples()}
        contexts = build_contexts(prep, analyzed, raw.items,
                                  raw.standard_rates, model_overrides, cfg,
                                  context_frame=context_frame)
        # the diagnosis belongs to every series, not only the scoped ones —
        # it is a property of the data and the card must always answer
        diagnoses = pd.DataFrame(
            [{"series_id": c.series_id, **c.diagnosis.to_row()}
             for c in contexts if c.diagnosis is not None])
        n_material = int(diagnoses["material"].sum()) if not diagnoses.empty \
            else 0
        if n_material:
            emit(f"Operating context materially changes {n_material} of "
                 f"{len(contexts)} series — context-aware models will compete "
                 "for those")
        # Scope restricts what gets FORECAST, never what gets analyzed: the
        # category priors above were pooled from every sibling series.
        if not cfg.scope.covers_all():
            wanted = set(cfg.scope.item_codes)
            in_scope = set(analyzed.loc[analyzed["item_code"].isin(wanted),
                                        "series_id"])
            contexts = [c for c in contexts if c.series_id in in_scope]
            if not contexts:
                raise RuntimeError(
                    "the selected items produced no forecastable series: "
                    f"{sorted(wanted)}")
            log.info("scope: %d series across %d item(s)",
                     len(contexts), len(wanted))
            emit(f"Scope: {len(contexts)} series across {len(wanted)} "
                 "selected item(s) — the rest of the catalogue was analyzed "
                 "but will not be forecast")
        else:
            emit(f"Scope: all {len(contexts)} series")
        if model_overrides:
            emit(f"Respecting {len(model_overrides)} locked model "
                 "override(s)")
        meta_by_series = analyzed.set_index("series_id")[
            ["line", "output_type", "last_period", "forecastability",
             "data_quality", "n_reliable", "trend_strength",
             "seasonality_strength", "is_orphan", "mode",
             "mode_source"]].to_dict("index")
        plan = plan_lookup(prep.driver_agg)

        progress("selecting and forecasting", 0.25)
        emit(f"Competing models on {len(contexts)} series "
             f"(in chunks of {CHUNK_SIZE})…")
        # Frozen (PyInstaller) apps must not spawn loky worker processes —
        # each worker would re-launch the exe. Threads are safe there;
        # numpy/statsmodels release the GIL enough to still parallelize.
        backend = "threading" if is_frozen() else "loky"
        results: list[dict] = []
        fit_started = time.perf_counter()
        with Parallel(n_jobs=cfg.n_jobs, batch_size=8, backend=backend) as pool:
            for start in range(0, len(contexts), CHUNK_SIZE):
                # a cancel request is honoured between chunks — mid-chunk
                # abort would leave worker processes orphaned
                if cancelled():
                    emit(f"Cancelled after {len(results)} of "
                         f"{len(contexts)} series — discarding partial "
                         "results")
                    _discard_partial(repo, run_id)
                    raise RunCancelled(run_id)
                chunk = contexts[start:start + CHUNK_SIZE]
                results.extend(pool(
                    delayed(_process_series)(
                        ctx, meta_by_series[ctx.series_id], cfg, plan)
                    for ctx in chunk))
                done = len(results)
                elapsed = time.perf_counter() - fit_started
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (len(contexts) - done) / rate if rate > 0 else 0
                n_failed = sum(1 for r in results if r["status"] != "ok")
                progress(f"forecasting {done}/{len(contexts)} series",
                         0.25 + 0.65 * done / len(contexts))
                emit(f"  {done}/{len(contexts)} series done "
                     f"({rate:.1f}/s, ~{remaining:.0f}s left"
                     + (f", {n_failed} failed)" if n_failed else ")"))

        emit(f"Model competition finished in "
             f"{time.perf_counter() - fit_started:.1f}s")
        if cancelled():
            emit("Cancelled before saving — discarding partial results")
            _discard_partial(repo, run_id)
            raise RunCancelled(run_id)

        progress("persisting results", 0.90)
        emit("Saving forecasts, model choices and explanations…")
        ok = [r for r in results if r["status"] == "ok"]
        failed = [r for r in results if r["status"] != "ok"]
        for r in failed:
            warnings.append(rules.ValidationWarning(
                code="SERIES_FAILED", severity=rules.Severity.WARNING,
                message=f"series {r['series_id']} failed: {r['error']}"))
        for r in ok:
            item, line, output = (r["series_id"].split("|") + [None, None])[:3]
            for code, message in r.get("caveats", []):
                warnings.append(rules.ValidationWarning(
                    code=code, severity=rules.Severity.INFO, message=message,
                    item_code=item or None, line=line or None,
                    output_type=output or None))

        _persist(repo, run_id, cfg, raw, prep, analyzed, ok, warnings,
                 diagnoses)
        duration = time.perf_counter() - started
        repo.finish_run(run_id, "complete", n_series=len(contexts),
                        duration_s=round(duration, 2))
        progress("done", 1.0)
        winners = {}
        for r in ok:
            name = r["selection"]["model_name"]
            winners[name] = winners.get(name, 0) + 1
        top = sorted(winners.items(), key=lambda kv: -kv[1])[:5]
        emit("Models chosen: " + ", ".join(f"{n}× {name}" for name, n in top)
             + (" …" if len(winners) > 5 else ""))
        if failed:
            emit(f"{len(failed)} series could not be forecast — see the "
                 "warnings on the Data page")
        emit(f"Run finished in {duration:.1f}s: {len(ok)} series forecast")
        log.info("run %s complete: %d series (%d failed) in %.1fs",
                 run_id, len(contexts), len(failed), duration)
        return run_id


def _discard_partial(repo: Repository, run_id: str | None) -> None:
    """A cancelled run leaves nothing behind: a half-finished forecast set
    must never be mistaken for a real one."""
    if run_id:
        repo.delete_run(run_id)


def _persist(repo: Repository, run_id: str, cfg: EngineConfig, raw, prep,
             analyzed: pd.DataFrame, ok: list[dict], warnings,
             diagnoses: pd.DataFrame | None = None) -> None:
    import json

    driver_store = prep.driver_agg.copy()
    if not driver_store.empty:
        driver_store["period"] = driver_store["period"].astype(str)
        driver_store = driver_store[["period", "line", "output_type",
                                     "driver_qty", "driver_uom", "driver_type"]]
    repo.replace_reference_data(
        raw.items.drop_duplicates("item_code"), driver_store,
        raw.standard_rates.drop_duplicates(["item_code", "line", "output_type"]))

    series_cols = [
        "series_id", "item_code", "line", "output_type", "mode", "mode_source",
        "target_uom", "first_period", "last_period", "n_periods", "n_observed",
        "n_reliable", "n_applicable", "is_orphan", "pattern_class", "adi", "cv2",
        "trend_strength", "seasonality_strength", "stationary", "autocorr_lag1",
        "outlier_pct", "missing_pct", "structural_break_period",
        "forecastability", "data_quality"]
    series_df = analyzed[series_cols].copy()
    series_df["stationary"] = series_df["stationary"].map(
        {True: 1, False: 0}).astype("Int64")
    repo.replace_series(series_df, prep.observations)
    repo.replace_series_context(
        diagnoses if diagnoses is not None else pd.DataFrame())

    if ok:
        val = pd.concat([r["validation"] for r in ok], ignore_index=True)
        val["run_id"] = run_id
        repo.write_validation_results(val)

        sel_rows = []
        for r in ok:
            s = r["selection"]
            sel_rows.append({
                "run_id": run_id, "series_id": s["series_id"],
                "model_name": s["model_name"], "window": s["window"],
                "mase": s["mase"], "confidence": s["confidence"],
                "confidence_label": s["confidence_label"],
                "route": s["route"], "reason_code": s["reason_code"],
                "reason_text": s["reason_text"],
                "rejected_json": json.dumps(s["rejected"]),
                "is_override": s["is_override"],
                "override_reason": s["override_reason"],
            })
        repo.write_selections(pd.DataFrame(sel_rows))

        fc = pd.concat([r["forecast"] for r in ok], ignore_index=True)
        fc["run_id"] = run_id
        fc = fc[["run_id", "series_id", "period", "target_value",
                 "lower_80", "upper_80", "lower_95", "upper_95",
                 "driver_plan", "reconstructed_demand",
                 "demand_lower_80", "demand_upper_80",
                 "demand_lower_95", "demand_upper_95", "confidence"]]
        repo.write_forecasts(fc)

    wdf = pd.DataFrame([{
        "series_id": (None if w.item_code is None else
                      f"{w.item_code}|{w.line or ''}|{w.output_type or ''}"),
        "code": w.code, "severity": w.severity.value, "count": w.count,
        "message": w.message} for w in warnings])
    repo.write_warnings(run_id, wdf)
