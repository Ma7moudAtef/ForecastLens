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

#: combined rate-scale interval bounds -> the atomic column each comes from.
#: The atomic bounds are on the TARGET scale, which for a Relative series is
#: the rate itself, so they combine the same way the rate does.
_RATE_BAND_SOURCE = {
    "rate_lower_80": "lower_80",
    "rate_upper_80": "upper_80",
    "rate_lower_95": "lower_95",
    "rate_upper_95": "upper_95",
}
RATE_BAND_COLUMNS = tuple(_RATE_BAND_SOURCE)


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
    the combined rate is the driver-weighted mean of the member rates.

    Interval bounds are carried through the SAME operator as the value they
    bracket: demand bounds are summed like demand, rate bounds are
    driver-weighted like the rate. Both assume the members' errors move
    together, which widens the band rather than narrowing it, and both are
    labelled as approximations in the UI.
    """
    bad = set(group_dims) - set(DIMENSIONS)
    if bad:
        raise ValueError(f"unknown dimensions: {bad}")
    df = forecasts.merge(series[["series_id", *DIMENSIONS]], on="series_id")
    df = _filter(df, filters)
    if df.empty:
        return pd.DataFrame(columns=["period", *group_dims, "demand",
                                     "driver_plan", "rate", *RATE_BAND_COLUMNS])
    df = df.copy()
    # Numerator/denominator of the driver-weighted mean rate. Both sum over
    # the same series-periods, so a driver shared by many items inflates
    # both and cancels — this is a weighted average of rates, not a ratio of
    # unrelated totals.
    df["_rate_x_driver"] = df["target_value"] * df["driver_plan"]
    df["_rate_weight"] = df["driver_plan"].where(df["target_value"].notna())
    # each bound is a rate in its own right, so it is weighted exactly like
    # the point rate — the band then brackets the combined point estimate for
    # the same reason each member bound brackets its own
    for bound, source in _RATE_BAND_SOURCE.items():
        df[f"_{bound}_x_driver"] = df[source] * df["_rate_weight"]
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
                confidence=("confidence", "mean"),
                **{f"_{b}_sum": (f"_{b}_x_driver", "sum")
                   for b in _RATE_BAND_SOURCE})
           .reset_index())
    with np.errstate(divide="ignore", invalid="ignore"):
        usable = agg["rate_weight"] > 0
        agg["rate"] = np.where(
            usable, agg["rate_weighted_numerator"] / agg["rate_weight"], np.nan)
        for bound in _RATE_BAND_SOURCE:
            agg[bound] = np.where(
                usable, agg[f"_{bound}_sum"] / agg["rate_weight"], np.nan)
    agg["driver_plan"] = _distinct_driver(df, keys, "driver_plan")
    return agg.drop(columns=["rate_weighted_numerator", "rate_weight",
                             *(f"_{b}_sum" for b in _RATE_BAND_SOURCE)])


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
