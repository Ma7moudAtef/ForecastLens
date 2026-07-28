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


def _distinct_driver(df: pd.DataFrame, keys: list[str],
                     column: str) -> np.ndarray:
    """Total driver for each group, counting a shared driver ONCE.

    The driver belongs to a (period, line, output_type), not to a series: 105
    items consumed on the same line share one production figure. Summing it
    per series multiplies it by the number of items — which is how a group of
    105 items reported 2,613 tonnes of production instead of 26.7.

    De-duplication happens WITHIN each group, never across groups: when the
    results are split by item, every item must still report the production of
    the line it runs on, not just whichever item happened to sort first.
    """
    subset = list(dict.fromkeys([*keys, "period", "line", "output_type"]))
    per_group = (df.drop_duplicates(subset=subset)
                 .groupby(keys, dropna=False)[column].sum())
    order = df.groupby(keys, dropna=False).size().index
    return per_group.reindex(order).to_numpy()


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
    df = df.copy()
    # Numerator/denominator of the driver-weighted mean rate. Both sum over
    # the same series-periods, so a driver shared by many items inflates
    # both and cancels — this is a weighted average of rates, not a ratio of
    # unrelated totals.
    df["_rate_x_driver"] = df["target_value"] * df["driver_plan"]
    df["_rate_weight"] = df["driver_plan"].where(df["target_value"].notna())
    keys = ["period", *group_dims]
    agg = (df.groupby(keys, dropna=False)
           .agg(demand=("reconstructed_demand", "sum"),
                demand_lower_80=("demand_lower_80", "sum"),
                demand_upper_80=("demand_upper_80", "sum"),
                demand_lower_95=("demand_lower_95", "sum"),
                demand_upper_95=("demand_upper_95", "sum"),
                rate_weighted_numerator=("_rate_x_driver", "sum"),
                rate_weight=("_rate_weight", "sum"),
                n_series=("series_id", "nunique"),
                confidence=("confidence", "mean"))
           .reset_index())
    with np.errstate(divide="ignore", invalid="ignore"):
        agg["rate"] = np.where(
            agg["rate_weight"] > 0,
            agg["rate_weighted_numerator"] / agg["rate_weight"], np.nan)
    agg["driver_plan"] = _distinct_driver(df, keys, "driver_plan")
    return agg.drop(columns=["rate_weighted_numerator", "rate_weight"])


def aggregate_observations(observations: pd.DataFrame, series: pd.DataFrame,
                           group_dims: list[str],
                           filters: dict[str, list] | None = None) -> pd.DataFrame:
    """Same group-by semantics for history.

    Quantities and driver are summed. The combined RATE is the driver-weighted
    average of the recorded rates, Σ(rateᵢ·driverᵢ) ÷ Σdriverᵢ.

    It is deliberately NOT Σqty_base ÷ Σdriver: `cons_rate` is whatever the
    source system defines it to be (per tonne, per day, per unit of a second
    measure…) and need not equal qty_base ÷ driver. Deriving the combined
    history rate from quantities instead of from the recorded rates put
    history on a different scale from the forecast — which is the same
    driver-weighted average of rates — and made the two incomparable on one
    chart.
    """
    bad = set(group_dims) - set(DIMENSIONS)
    if bad:
        raise ValueError(f"unknown dimensions: {bad}")
    df = observations.merge(series[["series_id", *DIMENSIONS]], on="series_id")
    df = _filter(df, filters)
    if df.empty:
        return pd.DataFrame(columns=["period", *group_dims, "qty_base",
                                     "driver_qty", "rate"])
    df = df.copy()
    # demand implied by the recorded rate — the numerator of the weighted mean
    df["_rate_x_driver"] = df["rate"] * df["driver_qty"]
    # driver only counts where a rate exists, or the weights and the values
    # would cover different periods
    df["_rate_driver"] = df["driver_qty"].where(df["rate"].notna())
    keys = ["period", *group_dims]
    agg = (df.groupby(keys, dropna=False)
           .agg(qty_base=("qty_base", "sum"),
                qty_ton=("qty_ton", "sum"),
                cost=("cost", "sum"),
                rate_weighted_numerator=("_rate_x_driver", "sum"),
                rate_weight=("_rate_driver", "sum"),
                n_series=("series_id", "nunique"))
           .reset_index())
    with np.errstate(divide="ignore", invalid="ignore"):
        agg["rate"] = np.where(
            agg["rate_weight"] > 0,
            agg["rate_weighted_numerator"] / agg["rate_weight"], np.nan)
    # the driver is shared by every item on the line — count it once
    agg["driver_qty"] = _distinct_driver(df, keys, "driver_qty")
    return agg.drop(columns=["rate_weighted_numerator", "rate_weight"])
