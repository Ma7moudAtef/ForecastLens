"""A combined Relative view must show its 80% and 95% ranges.

An aggregate point estimate with no interval is worse than no aggregate: it
looks exactly as certain as a single well-behaved series.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.forecast.aggregate import RATE_BAND_COLUMNS, aggregate_forecasts


def _series(n=2):
    return pd.DataFrame({
        "series_id": [f"i{k}|L1|X" for k in range(n)],
        "item_code": [f"i{k}" for k in range(n)],
        "line": ["L1"] * n, "output_type": ["X"] * n})


_FORECAST_COLUMNS = [
    "series_id", "period", "target_value", "lower_80", "upper_80",
    "lower_95", "upper_95", "driver_plan", "reconstructed_demand",
    "demand_lower_80", "demand_upper_80", "demand_lower_95",
    "demand_upper_95", "confidence"]


def _forecasts(rates, drivers, spread=0.2):
    """One future period per row set; bounds a fixed fraction either side."""
    rows = []
    for k, (rate, driver) in enumerate(zip(rates, drivers)):
        rows.append({
            "series_id": f"i{k}|L1|X", "period": "2026-01",
            "target_value": rate,
            "lower_80": rate * (1 - spread), "upper_80": rate * (1 + spread),
            "lower_95": rate * (1 - 2 * spread), "upper_95": rate * (1 + 2 * spread),
            "driver_plan": driver,
            "reconstructed_demand": rate * driver,
            "demand_lower_80": rate * (1 - spread) * driver,
            "demand_upper_80": rate * (1 + spread) * driver,
            "demand_lower_95": rate * (1 - 2 * spread) * driver,
            "demand_upper_95": rate * (1 + 2 * spread) * driver,
            "confidence": 0.5})
    return pd.DataFrame(rows, columns=_FORECAST_COLUMNS)


def test_rate_bands_are_produced():
    agg = aggregate_forecasts(_forecasts([5.0, 9.0], [100.0, 300.0]),
                              _series(), group_dims=[])
    for column in RATE_BAND_COLUMNS:
        assert column in agg.columns, f"{column} missing"
        assert agg[column].notna().all()


def test_rate_bands_are_driver_weighted_exactly_like_the_rate():
    """Each bound is itself a rate, so it combines the same way the point
    estimate does — not by summing, which would leave the band on a different
    scale from the line it is supposed to bracket."""
    rates, drivers = [5.0, 9.0], [100.0, 300.0]
    agg = aggregate_forecasts(_forecasts(rates, drivers), _series(),
                              group_dims=[]).iloc[0]

    weighted = np.average(rates, weights=drivers)
    assert agg["rate"] == pytest.approx(weighted)
    assert agg["rate_lower_80"] == pytest.approx(
        np.average([r * 0.8 for r in rates], weights=drivers))
    assert agg["rate_upper_95"] == pytest.approx(
        np.average([r * 1.4 for r in rates], weights=drivers))


def test_the_band_brackets_the_combined_point_estimate():
    agg = aggregate_forecasts(
        _forecasts([5.0, 9.0, 2.0], [100.0, 300.0, 50.0]),
        _series(3), group_dims=[]).iloc[0]

    assert agg["rate_lower_95"] <= agg["rate_lower_80"] <= agg["rate"]
    assert agg["rate"] <= agg["rate_upper_80"] <= agg["rate_upper_95"]


def test_a_period_with_no_production_plan_has_no_rate_and_no_band():
    """No plan means no weight, so there is nothing to average — and an
    invented band would be worse than an empty one."""
    fc = _forecasts([5.0], [np.nan])
    agg = aggregate_forecasts(fc, _series(1), group_dims=[]).iloc[0]

    assert pd.isna(agg["rate"])
    for column in RATE_BAND_COLUMNS:
        assert pd.isna(agg[column])


def test_bands_survive_grouping_by_a_dimension():
    fc = _forecasts([5.0, 9.0], [100.0, 300.0])
    agg = aggregate_forecasts(fc, _series(), group_dims=["item_code"])
    assert len(agg) == 2
    for column in RATE_BAND_COLUMNS:
        assert agg[column].notna().all()
    # one series per group, so the "weighted mean" is just that series' bound
    assert sorted(agg["rate_lower_80"].round(6)) == [4.0, 7.2]


def test_the_empty_frame_still_declares_the_band_columns():
    """The caller renames these columns for the chart; a frame without them
    raises instead of drawing an empty chart."""
    empty = _forecasts([], []).astype({"series_id": "object"})
    agg = aggregate_forecasts(empty, _series(0).astype({"series_id": "object"}),
                              group_dims=[])
    assert agg.empty
    for column in RATE_BAND_COLUMNS:
        assert column in agg.columns
