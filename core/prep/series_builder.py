"""Atomic series construction.

The forecasting unit is (item_code, line, output_type). This module turns raw
consumption rows into one continuous, gap-filled, calendar-normalized series
per atomic key, joined to its actual driver, with reliability flags.

Rules applied here:
- duplicate rows within a (series, period) are summed into one observation
- missing periods between first and last observation become explicit
  zero-demand rows flagged is_gap_filled (no demand ≠ no data)
- Relative target = rate; Absolute target = qty_base / days-in-period
- driver reliability guard: a period whose driver is below
  floor_fraction × series-median driver is unreliable; rates against a
  near-zero denominator explode. Division by zero is handled, never crashes.
- Relative periods with no actual driver record are unreliable data gaps —
  they NEVER change the series' mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.config import EngineConfig
from core.io.schema import RawTables
from core.prep import driver as drv
from core.prep.calendar import days_in_period, full_range, to_period_index
from core.prep.mode import Mode, ModeSource, resolve_mode
from core.store.repository import series_id_of
from core.validate.rules import Severity, ValidationWarning

SERIES_KEY = ["item_code", "line", "output_type"]


@dataclass
class PreparedData:
    """Everything downstream stages need, at the atomic grain."""

    series: pd.DataFrame        # one row per atomic series (metadata)
    observations: pd.DataFrame  # one row per (series, period)
    driver_agg: pd.DataFrame    # driver at configured granularity, actual+plan
    warnings: list[ValidationWarning] = field(default_factory=list)


def _norm(v) -> str | None:
    return None if pd.isna(v) else str(v)


def build_series(raw: RawTables, cfg: EngineConfig,
                 mode_overrides: dict[str, str] | None = None) -> PreparedData:
    mode_overrides = mode_overrides or {}
    warnings: list[ValidationWarning] = []

    driver_agg = drv.aggregate_driver(raw.driver, cfg.granularity)
    actual_lookup = drv.actual_driver_lookup(driver_agg)
    combos = drv.driver_combos(driver_agg)

    declared_bom = (
        raw.items.dropna(subset=["item_code"])
        .drop_duplicates("item_code")
        .set_index("item_code")["declared_mode"]
        .to_dict())
    item_uom = (
        raw.items.dropna(subset=["item_code"])
        .drop_duplicates("item_code")
        .set_index("item_code")["uom"]
        .to_dict())

    cons = raw.consumption.copy()
    cons["period"] = to_period_index(cons["date"], cfg.granularity)

    series_rows: list[dict] = []
    obs_frames: list[pd.DataFrame] = []

    for key, grp in cons.groupby(SERIES_KEY, dropna=False):
        item, line, output = (_norm(k) for k in key)
        sid = series_id_of(item, line, output)

        has_rate = grp["rate"].notna().any()
        mode, mode_source = resolve_mode(
            has_rate,
            declared_bom=_norm(declared_bom.get(item)),
            declared_ui=mode_overrides.get(item),
        )

        # -- aggregate duplicates to one row per period ----------------------
        agg = grp.groupby("period").agg(
            qty_base=("qty_base", "sum"),
            qty_ton=("qty_ton", "sum"),
            cost=("cost", "sum"),
            rate=("rate", lambda s: s.sum() if s.notna().any() else np.nan),
        )

        # -- continuous period index, explicit zero-demand gap rows ----------
        periods = full_range(agg.index.min(), agg.index.max())
        obs = agg.reindex(periods)
        is_gap = obs["qty_base"].isna()
        obs[["qty_base", "qty_ton", "cost"]] = (
            obs[["qty_base", "qty_ton", "cost"]].fillna(0.0))
        if mode is Mode.RELATIVE:
            obs["rate"] = obs["rate"].fillna(0.0)

        # -- driver join (relative only; absolute ignores the driver) --------
        is_orphan = False
        if mode is Mode.RELATIVE:
            obs["driver_qty"] = [
                actual_lookup.get((p, line, output), np.nan) for p in periods]
            is_orphan = (line, output) not in combos
        else:
            obs["driver_qty"] = np.nan

        # -- target ----------------------------------------------------------
        days = np.asarray(days_in_period(periods), dtype=float)
        if mode is Mode.RELATIVE:
            obs["target"] = obs["rate"]
        else:
            obs["target"] = obs["qty_base"] / days  # per-day normalization

        # -- reliability -----------------------------------------------------
        reliable = np.ones(len(obs), dtype=bool)
        if mode is Mode.RELATIVE:
            dq = obs["driver_qty"].to_numpy(dtype=float)
            missing_driver = np.isnan(dq)
            with np.errstate(invalid="ignore"):
                median_driver = np.nanmedian(dq) if not np.all(missing_driver) else np.nan
            # a non-positive driver is always unreliable — the rate divides by
            # (near-)zero — independent of the relative floor
            nonpositive = ~missing_driver & (dq <= 0)
            if np.isnan(median_driver):
                low_driver = nonpositive
            else:
                floor = cfg.driver.floor_fraction * median_driver
                low_driver = nonpositive | (~missing_driver & (dq < floor))
            reliable = ~missing_driver & ~low_driver

            n_low = int(low_driver.sum())
            if n_low:
                warnings.append(ValidationWarning(
                    code="LOW_DRIVER_PERIODS", severity=Severity.WARNING,
                    count=n_low, item_code=item, line=line, output_type=output,
                    message=(f"{n_low} period(s) have driver quantity below "
                             f"{cfg.driver.floor_fraction:.0%} of the series' median "
                             "driver. Rates against a near-zero denominator are "
                             "unreliable; these periods are excluded from fitting.")))

        obs_out = pd.DataFrame({
            "series_id": sid,
            "period": [str(p) for p in periods],
            "qty_base": obs["qty_base"].to_numpy(dtype=float),
            "qty_ton": obs["qty_ton"].to_numpy(dtype=float),
            "cost": obs["cost"].to_numpy(dtype=float),
            "rate": obs["rate"].to_numpy(dtype=float),
            "driver_qty": obs["driver_qty"].to_numpy(dtype=float),
            "target": obs["target"].to_numpy(dtype=float),
            "is_gap_filled": is_gap.to_numpy(dtype=bool).astype(int),
            "is_reliable": reliable.astype(int),
        })
        obs_frames.append(obs_out)

        rate_uoms = grp["rate_uom"].dropna()
        target_uom = (rate_uoms.mode().iloc[0] if mode is Mode.RELATIVE and
                      len(rate_uoms) else item_uom.get(item))

        series_rows.append({
            "series_id": sid,
            "item_code": item,
            "line": line,
            "output_type": output,
            "mode": mode.value,
            "mode_source": mode_source.value,
            "target_uom": _norm(target_uom),
            "first_period": str(periods[0]),
            "last_period": str(periods[-1]),
            "n_periods": len(periods),
            "n_observed": int((~is_gap).sum()),
            "n_reliable": int(reliable.sum()),
            "is_orphan": int(is_orphan),
        })

    series = pd.DataFrame(series_rows)
    observations = pd.concat(obs_frames, ignore_index=True)
    return PreparedData(series=series, observations=observations,
                        driver_agg=driver_agg, warnings=warnings)
