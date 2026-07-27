"""Demand reconstruction: target scale → demand quantities.

Absolute: per-day forecast × the target period's day count.
Relative:  forecast rate × the driver PLAN for that (period, line, output).

An orphan series (no driver combo at all) or a period with no plan yields
reconstructed_demand = NaN — never a guessed denominator. Partial plan
periods are used as-is; they were flagged at aggregation time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import EngineConfig
from core.prep.calendar import days_in_period, parse_period
from core.prep.mode import Mode


def plan_lookup(driver_agg: pd.DataFrame) -> dict[tuple, float]:
    plan = driver_agg[driver_agg["driver_type"] == "plan"]
    return {(str(r.period), r.line, r.output_type): float(r.driver_qty)
            for r in plan.itertuples()}


_BOUND_COLS = ["lower_80", "upper_80", "lower_95", "upper_95"]


def reconstruct(forecast: pd.DataFrame, mode: str, line, output_type,
                plan: dict[tuple, float], cfg: EngineConfig) -> pd.DataFrame:
    """Add driver_plan, reconstructed_demand and demand-scale interval
    columns to a forecast frame. The multiplier (day count or planned driver)
    is treated as known, so bounds scale with the point forecast."""
    out = forecast.copy()
    if mode == Mode.ABSOLUTE.value:
        periods = pd.PeriodIndex(
            [parse_period(p, cfg.granularity) for p in out["period"]])
        multiplier = np.asarray(days_in_period(periods), dtype=float)
        out["driver_plan"] = np.nan
    else:
        multiplier = np.array([plan.get((p, line, output_type), np.nan)
                               for p in out["period"]], dtype=float)
        out["driver_plan"] = multiplier
    out["reconstructed_demand"] = out["target_value"].to_numpy() * multiplier
    for col in _BOUND_COLS:
        out[f"demand_{col}"] = out[col].to_numpy() * multiplier
    return out
