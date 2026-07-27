"""Aggregation across dimensions — the dimension picker's engine.

RULES (Trap 1):
  1. Reconstruct demand for every atomic series first.
  2. SUM the demand.
  3. A combined rate, when displayed, is Σdemand ÷ Σdriver — a
     driver-weighted average. NEVER sum rates, never average them unweighted.

The picker is a pure GROUP BY over already-computed atomic results — never a
re-fit. An omitted dimension simply is not in the group key, which makes the
historical "output B, no line returned 2 rows" bug structurally impossible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DIMENSIONS = ["item_code", "line", "output_type"]


def _filter(df: pd.DataFrame, filters: dict[str, list] | None) -> pd.DataFrame:
    if not filters:
        return df
    for dim, values in filters.items():
        if values:
            df = df[df[dim].isin(values)]
    return df


def aggregate_forecasts(forecasts: pd.DataFrame, series: pd.DataFrame,
                        group_dims: list[str],
                        filters: dict[str, list] | None = None) -> pd.DataFrame:
    """Group atomic forecasts. `group_dims` ⊆ {item_code, line, output_type};
    omitted dimensions are combined across. Demand and driver are summed;
    the combined rate is Σdemand/Σdriver. Interval bounds are summed — an
    approximation that ignores cross-series error correlation, and is
    labelled as such in the UI."""
    bad = set(group_dims) - set(DIMENSIONS)
    if bad:
        raise ValueError(f"unknown dimensions: {bad}")
    df = forecasts.merge(series[["series_id", *DIMENSIONS]], on="series_id")
    df = _filter(df, filters)
    if df.empty:
        return pd.DataFrame(columns=["period", *group_dims, "demand",
                                     "driver_plan", "rate"])
    keys = ["period", *group_dims]
    agg = (df.groupby(keys, dropna=False)
           .agg(demand=("reconstructed_demand", "sum"),
                demand_lower_80=("demand_lower_80", "sum"),
                demand_upper_80=("demand_upper_80", "sum"),
                demand_lower_95=("demand_lower_95", "sum"),
                demand_upper_95=("demand_upper_95", "sum"),
                driver_plan=("driver_plan", "sum"),
                n_series=("series_id", "nunique"),
                confidence=("confidence", "mean"))
           .reset_index())
    with np.errstate(divide="ignore", invalid="ignore"):
        agg["rate"] = np.where(agg["driver_plan"] > 0,
                               agg["demand"] / agg["driver_plan"], np.nan)
    return agg


def aggregate_observations(observations: pd.DataFrame, series: pd.DataFrame,
                           group_dims: list[str],
                           filters: dict[str, list] | None = None) -> pd.DataFrame:
    """Same group-by semantics for history: quantities and driver are summed,
    the combined rate is Σqty/Σdriver."""
    bad = set(group_dims) - set(DIMENSIONS)
    if bad:
        raise ValueError(f"unknown dimensions: {bad}")
    df = observations.merge(series[["series_id", *DIMENSIONS]], on="series_id")
    df = _filter(df, filters)
    if df.empty:
        return pd.DataFrame(columns=["period", *group_dims, "qty_base",
                                     "driver_qty", "rate"])
    keys = ["period", *group_dims]
    agg = (df.groupby(keys, dropna=False)
           .agg(qty_base=("qty_base", "sum"),
                qty_ton=("qty_ton", "sum"),
                cost=("cost", "sum"),
                driver_qty=("driver_qty", "sum"),
                n_series=("series_id", "nunique"))
           .reset_index())
    with np.errstate(divide="ignore", invalid="ignore"):
        agg["rate"] = np.where(agg["driver_qty"] > 0,
                               agg["qty_base"] / agg["driver_qty"], np.nan)
    return agg
