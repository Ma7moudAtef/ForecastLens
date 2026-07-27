"""Driver aggregation and joining.

The driver plan may arrive at a finer granularity than consumption (daily
plan vs monthly history in the sample). It is aggregated to the configured
period by SUMMING before any rate multiplication. Partial periods at the
plan boundary are flagged explicitly rather than silently under-counted.
"""
from __future__ import annotations

import pandas as pd

from core.config import Granularity
from core.prep.calendar import days_in_period, to_period_index

DRIVER_KEY = ["period", "line", "output_type"]


def aggregate_driver(driver: pd.DataFrame, granularity: Granularity) -> pd.DataFrame:
    """Aggregate raw driver rows to (period, line, output_type, driver_type).

    Returns columns: period (pd.Period), line, output_type, driver_type,
    driver_qty (summed), driver_uom, n_days_observed, is_partial.
    """
    if driver.empty:
        return pd.DataFrame(columns=[*DRIVER_KEY, "driver_type", "driver_qty",
                                     "driver_uom", "n_days_observed", "is_partial"])
    d = driver[driver["driver_type"].isin(["actual", "plan"])].copy()
    d["period"] = to_period_index(d["date"], granularity)
    grouped = (
        d.groupby(["period", "line", "output_type", "driver_type"], dropna=False)
        .agg(driver_qty=("driver_qty", "sum"),
             driver_uom=("driver_uom", "first"),
             n_days_observed=("date", lambda s: s.dt.normalize().nunique()))
        .reset_index())
    period_days = days_in_period(pd.PeriodIndex(grouped["period"]))
    # A source finer than the period (daily plan) only covers the period fully
    # when every day is present. A source already at period grain (one row per
    # period) is complete by definition.
    grouped["is_partial"] = (grouped["n_days_observed"] > 1) & (
        grouped["n_days_observed"] < period_days)
    return grouped


def actual_driver_lookup(agg: pd.DataFrame) -> dict[tuple, float]:
    """(period, line, output_type) -> actual driver quantity."""
    act = agg[agg["driver_type"] == "actual"]
    return {
        (r.period, r.line, r.output_type): r.driver_qty
        for r in act.itertuples()
    }


def driver_combos(agg: pd.DataFrame) -> set[tuple]:
    """Every (line, output_type) that has any driver record of any type."""
    if agg.empty:
        return set()
    return set(zip(agg["line"], agg["output_type"]))
