"""Combined-view arithmetic: history and forecast must be on ONE scale, and
a shared driver must be counted once.

Regression: the combined history rate was derived as Σqty_base ÷ Σdriver,
while the forecast rate is the driver-weighted average of the recorded rates.
`cons_rate` need not equal qty_base ÷ driver — in real data it may be per
tonne, per day, or per a second measure entirely — so the two sat on
different scales (off by 5–50× on the sample workbook, 1000× when the unit
differs by a factor of 1000) and could not be compared on one chart.
"""
import numpy as np
import pandas as pd
import pytest

from core.forecast.aggregate import aggregate_forecasts, aggregate_observations

# Two items consumed on the SAME line and output, so they share one driver.
# cons_rate is deliberately NOT qty_base/driver — it is qty_ton/days here,
# exactly like the sample workbook — so a quantity-derived rate would be off
# by the unit factor.
SERIES = pd.DataFrame([
    {"series_id": "A|L1|X", "item_code": "A", "line": "L1", "output_type": "X",
     "mode": "relative"},
    {"series_id": "B|L1|X", "item_code": "B", "line": "L1", "output_type": "X",
     "mode": "relative"},
])

DRIVER = 100.0
OBS = pd.DataFrame([
    # qty_base is in kilograms (1000× the tonnes the rate is based on)
    {"series_id": "A|L1|X", "period": "2026-01", "qty_base": 2000.0,
     "qty_ton": 2.0, "cost": 0.0, "rate": 0.02, "driver_qty": DRIVER,
     "target": 0.02, "is_gap_filled": 0, "is_reliable": 1, "is_applicable": 1},
    {"series_id": "B|L1|X", "period": "2026-01", "qty_base": 6000.0,
     "qty_ton": 6.0, "cost": 0.0, "rate": 0.06, "driver_qty": DRIVER,
     "target": 0.06, "is_gap_filled": 0, "is_reliable": 1, "is_applicable": 1},
])


def _forecast_row(sid, rate, plan):
    return {"series_id": sid, "period": "2026-02", "target_value": rate,
            "lower_80": rate, "upper_80": rate, "lower_95": rate,
            "upper_95": rate, "driver_plan": plan,
            "reconstructed_demand": rate * plan,
            "demand_lower_80": rate * plan, "demand_upper_80": rate * plan,
            "demand_lower_95": rate * plan, "demand_upper_95": rate * plan,
            "confidence": 0.8}


FC = pd.DataFrame([_forecast_row("A|L1|X", 0.02, DRIVER),
                   _forecast_row("B|L1|X", 0.06, DRIVER)])


def test_history_rate_is_the_driver_weighted_mean_of_recorded_rates():
    agg = aggregate_observations(OBS, SERIES, group_dims=[])
    assert len(agg) == 1
    expected = (0.02 * DRIVER + 0.06 * DRIVER) / (DRIVER + DRIVER)
    assert agg.iloc[0]["rate"] == pytest.approx(expected)   # 0.04


def test_history_rate_is_not_derived_from_quantities():
    """The old formula (Σqty_base ÷ Σdriver) would give 80 — a scale error of
    2000×, which is exactly the reported symptom."""
    agg = aggregate_observations(OBS, SERIES, group_dims=[])
    quantity_derived = OBS["qty_base"].sum() / (2 * DRIVER)
    assert quantity_derived == pytest.approx(40.0)
    assert agg.iloc[0]["rate"] != pytest.approx(quantity_derived)
    assert agg.iloc[0]["rate"] < 1.0


def test_history_and_forecast_rates_share_one_scale():
    hist = aggregate_observations(OBS, SERIES, group_dims=[]).iloc[0]["rate"]
    fore = aggregate_forecasts(FC, SERIES, group_dims=[]).iloc[0]["rate"]
    # same members, same rates, same driver → the two must agree exactly
    assert fore == pytest.approx(hist)


def test_forecast_rate_is_driver_weighted_not_plain_average():
    fc = pd.DataFrame([_forecast_row("A|L1|X", 1.0, 10.0),
                       _forecast_row("B|L1|X", 0.01, 1000.0)])
    agg = aggregate_forecasts(fc, SERIES, group_dims=[])
    weighted = (1.0 * 10 + 0.01 * 1000) / (10 + 1000)
    assert agg.iloc[0]["rate"] == pytest.approx(weighted)
    assert agg.iloc[0]["rate"] != pytest.approx((1.0 + 0.01) / 2)


def test_shared_driver_is_counted_once_not_once_per_item():
    """Both items run on line L1/output X, so the group's driver is 100 —
    not 200. Summing per series reported a line producing twice (or, with
    105 items, 105×) what it actually produced."""
    hist = aggregate_observations(OBS, SERIES, group_dims=[]).iloc[0]
    fore = aggregate_forecasts(FC, SERIES, group_dims=[]).iloc[0]
    assert hist["driver_qty"] == pytest.approx(DRIVER)
    assert fore["driver_plan"] == pytest.approx(DRIVER)
    assert hist["n_series"] == 2         # …while still covering both items


def test_distinct_drivers_on_different_lines_do_add_up():
    series = pd.DataFrame([
        {"series_id": "A|L1|X", "item_code": "A", "line": "L1",
         "output_type": "X", "mode": "relative"},
        {"series_id": "C|L2|X", "item_code": "C", "line": "L2",
         "output_type": "X", "mode": "relative"},
    ])
    obs = pd.DataFrame([
        {"series_id": "A|L1|X", "period": "2026-01", "qty_base": 1.0,
         "qty_ton": 1.0, "cost": 0.0, "rate": 0.02, "driver_qty": 100.0,
         "target": 0.02, "is_gap_filled": 0, "is_reliable": 1,
         "is_applicable": 1},
        {"series_id": "C|L2|X", "period": "2026-01", "qty_base": 1.0,
         "qty_ton": 1.0, "cost": 0.0, "rate": 0.04, "driver_qty": 50.0,
         "target": 0.04, "is_gap_filled": 0, "is_reliable": 1,
         "is_applicable": 1},
    ])
    agg = aggregate_observations(obs, series, group_dims=[]).iloc[0]
    assert agg["driver_qty"] == pytest.approx(150.0)      # two real lines
    assert agg["rate"] == pytest.approx(
        (0.02 * 100 + 0.04 * 50) / 150)


def test_each_item_keeps_its_line_driver_when_split_by_item():
    """De-duplication must happen within a group, not across groups: split by
    item, BOTH items on the shared line still report that line's driver."""
    agg = aggregate_observations(OBS, SERIES, group_dims=["item_code"])
    assert len(agg) == 2
    assert set(agg["item_code"]) == {"A", "B"}
    assert agg["driver_qty"].tolist() == pytest.approx([DRIVER, DRIVER])
    assert agg.set_index("item_code").loc["A", "rate"] == pytest.approx(0.02)
    assert agg.set_index("item_code").loc["B", "rate"] == pytest.approx(0.06)

    fc = aggregate_forecasts(FC, SERIES, group_dims=["item_code"])
    assert fc["driver_plan"].tolist() == pytest.approx([DRIVER, DRIVER])


def test_item_on_two_lines_sums_both_line_drivers():
    series = pd.DataFrame([
        {"series_id": "A|L1|X", "item_code": "A", "line": "L1",
         "output_type": "X", "mode": "relative"},
        {"series_id": "A|L2|X", "item_code": "A", "line": "L2",
         "output_type": "X", "mode": "relative"},
    ])
    obs = pd.DataFrame([
        {"series_id": "A|L1|X", "period": "2026-01", "qty_base": 1.0,
         "qty_ton": 1.0, "cost": 0.0, "rate": 0.02, "driver_qty": 100.0,
         "target": 0.02, "is_gap_filled": 0, "is_reliable": 1,
         "is_applicable": 1},
        {"series_id": "A|L2|X", "period": "2026-01", "qty_base": 1.0,
         "qty_ton": 1.0, "cost": 0.0, "rate": 0.02, "driver_qty": 40.0,
         "target": 0.02, "is_gap_filled": 0, "is_reliable": 1,
         "is_applicable": 1},
    ])
    agg = aggregate_observations(obs, series, group_dims=["item_code"]).iloc[0]
    assert agg["driver_qty"] == pytest.approx(140.0)


def test_demand_is_still_a_plain_sum():
    """Quantities add across items; only the driver and the rate are special."""
    agg = aggregate_forecasts(FC, SERIES, group_dims=[]).iloc[0]
    assert agg["demand"] == pytest.approx(0.02 * DRIVER + 0.06 * DRIVER)


def test_periods_without_a_rate_do_not_pollute_the_weighted_mean():
    obs = pd.concat([OBS, pd.DataFrame([{
        "series_id": "A|L1|X", "period": "2026-02", "qty_base": 0.0,
        "qty_ton": 0.0, "cost": 0.0, "rate": np.nan, "driver_qty": 500.0,
        "target": 0.0, "is_gap_filled": 1, "is_reliable": 0,
        "is_applicable": 0}])], ignore_index=True)
    agg = aggregate_observations(obs, SERIES, group_dims=[])
    feb = agg[agg["period"] == "2026-02"].iloc[0]
    assert pd.isna(feb["rate"])          # no rate recorded → no combined rate
    jan = agg[agg["period"] == "2026-01"].iloc[0]
    assert jan["rate"] == pytest.approx(0.04)
