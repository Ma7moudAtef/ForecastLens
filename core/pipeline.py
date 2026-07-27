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
from core.prep.calendar import parse_period
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


def _noop_progress(stage: str, fraction: float) -> None:
    pass


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
                   cfg: EngineConfig) -> list[SeriesContext]:
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
        driver = g["driver_qty"].to_numpy(dtype=float) \
            if row.mode == Mode.RELATIVE.value else None
        prior_value, prior_level, prior_siblings, prior_cat = _prior_for(
            row.item_code, row.mode, items_idx, pools)
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
                    "mase": r.mase, "status": r.status}
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
                 run_name: str | None = None) -> str:
    """Execute a full batch run and persist everything. Returns run_id."""
    cfg = cfg or EngineConfig()
    progress = progress_cb or _noop_progress
    db_path = db_path or AppConfig().db_path
    started = time.perf_counter()

    with Repository(db_path) as repo:
        progress("loading workbook", 0.02)
        raw = ExcelSource(input_path).load()
        input_hash = hashlib.sha256(Path(input_path).read_bytes()).hexdigest()[:16]

        progress("validating", 0.06)
        warnings = rules.run_all(raw, cfg)
        if rules.has_fatal(warnings):
            fatal = [w.message for w in warnings if w.severity == rules.Severity.FATAL]
            raise RuntimeError("fatal validation errors: " + "; ".join(fatal))

        progress("building series", 0.12)
        mode_overrides = {
            r.item_code: r.mode for r in repo.get_mode_overrides().itertuples()}
        prep = build_series(raw, cfg, mode_overrides=mode_overrides)
        warnings = warnings + prep.warnings

        progress("analyzing behaviour", 0.20)
        analyzed = analyze_all(prep, cfg)

        run_id = repo.create_run(cfg.model_dump_json(), source_name=raw.source_name,
                                 input_hash=input_hash, name=run_name)

        model_overrides = {
            r.series_id: r.model_name
            for r in repo.get_model_overrides().itertuples()}
        contexts = build_contexts(prep, analyzed, raw.items,
                                  raw.standard_rates, model_overrides, cfg)
        meta_by_series = analyzed.set_index("series_id")[
            ["line", "output_type", "last_period", "forecastability",
             "data_quality", "n_reliable", "trend_strength",
             "seasonality_strength", "is_orphan", "mode",
             "mode_source"]].to_dict("index")
        plan = plan_lookup(prep.driver_agg)

        progress("selecting and forecasting", 0.25)
        # Frozen (PyInstaller) apps must not spawn loky worker processes —
        # each worker would re-launch the exe. Threads are safe there;
        # numpy/statsmodels release the GIL enough to still parallelize.
        backend = "threading" if getattr(sys, "frozen", False) else "loky"
        results = Parallel(n_jobs=cfg.n_jobs, batch_size=16, backend=backend)(
            delayed(_process_series)(ctx, meta_by_series[ctx.series_id], cfg, plan)
            for ctx in contexts)

        progress("persisting results", 0.90)
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

        _persist(repo, run_id, cfg, raw, prep, analyzed, ok, warnings)
        duration = time.perf_counter() - started
        repo.finish_run(run_id, "complete", n_series=len(analyzed),
                        duration_s=round(duration, 2))
        progress("done", 1.0)
        log.info("run %s complete: %d series (%d failed) in %.1fs",
                 run_id, len(analyzed), len(failed), duration)
        return run_id


def _persist(repo: Repository, run_id: str, cfg: EngineConfig, raw, prep,
             analyzed: pd.DataFrame, ok: list[dict], warnings) -> None:
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
        "n_reliable", "is_orphan", "pattern_class", "adi", "cv2",
        "trend_strength", "seasonality_strength", "stationary", "autocorr_lag1",
        "outlier_pct", "missing_pct", "structural_break_period",
        "forecastability", "data_quality"]
    series_df = analyzed[series_cols].copy()
    series_df["stationary"] = series_df["stationary"].map(
        {True: 1, False: 0}).astype("Int64")
    repo.replace_series(series_df, prep.observations)

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
