"""Trap 1 — Rate arithmetic.

Combining two series must sum reconstructed demand, never rates. The fixture
uses drivers different by two orders of magnitude, so the naive average of
rates gives a VISIBLY different answer than the correct driver-weighted one.
"""
import numpy as np
import pandas as pd
import pytest

from core.forecast.aggregate import aggregate_forecasts


def _forecast_frame(series_id, period, rate, driver):
    return {
        "series_id": series_id, "period": period,
        "target_value": rate,
        "lower_80": rate, "upper_80": rate, "lower_95": rate, "upper_95": rate,
        "driver_plan": driver,
        "reconstructed_demand": rate * driver,
        "demand_lower_80": rate * driver, "demand_upper_80": rate * driver,
        "demand_lower_95": rate * driver, "demand_upper_95": rate * driver,
        "confidence": 0.8,
    }


# Series A: rate 1.0 on a tiny driver (10). Series B: rate 0.01 on a huge
# driver (1000). Naive average rate = 0.505; true combined = 20/1010 ≈ 0.0198.
SERIES = pd.DataFrame([
    {"series_id": "A|l1|x", "item_code": "A", "line": "l1", "output_type": "x"},
    {"series_id": "B|l1|x", "item_code": "B", "line": "l1", "output_type": "x"},
])
FC = pd.DataFrame([
    _forecast_frame("A|l1|x", "2026-07", 1.0, 10.0),
    _forecast_frame("B|l1|x", "2026-07", 0.01, 1000.0),
])


def test_combined_demand_is_the_sum_of_demands():
    out = aggregate_forecasts(FC, SERIES, group_dims=["line"])
    assert len(out) == 1
    row = out.iloc[0]
    assert row["demand"] == pytest.approx(1.0 * 10 + 0.01 * 1000)  # 20.0


def test_combined_rate_is_driver_weighted_not_averaged():
    out = aggregate_forecasts(FC, SERIES, group_dims=["line"])
    row = out.iloc[0]
    true_rate = (1.0 * 10 + 0.01 * 1000) / (10 + 1000)
    naive_average = (1.0 + 0.01) / 2
    assert row["rate"] == pytest.approx(true_rate)          # ≈ 0.0198
    assert abs(row["rate"] - naive_average) > 0.4           # visibly different


def test_rates_are_never_summed():
    out = aggregate_forecasts(FC, SERIES, group_dims=["line"])
    assert out.iloc[0]["rate"] < 1.0                        # Σrates would be 1.01


# --- dimension picker semantics (§5 of the build prompt) ----------------------

def _picker_fixture():
    series = pd.DataFrame([
        {"series_id": f"i{i}|{ln}|{ot}", "item_code": f"i{i}",
         "line": ln, "output_type": ot}
        for i, (ln, ot) in enumerate([
            ("1", "B"), ("2", "B"), ("1", "F"), ("2", "F")])
    ])
    fc = pd.DataFrame([
        _forecast_frame(sid, "2026-07", 0.5, 100.0)
        for sid in series["series_id"]])
    return fc, series


def test_output_b_no_line_returns_exactly_one_row():
    """The historical bug: 'B, no line' returned 2 rows. Group-by semantics —
    an omitted dimension is not in the key — make it structurally impossible."""
    fc, series = _picker_fixture()
    out = aggregate_forecasts(fc, series, group_dims=["output_type"],
                              filters={"output_type": ["B"]})
    assert len(out) == 1
    assert out.iloc[0]["demand"] == pytest.approx(100.0)  # both lines combined


def test_picker_row_counts_match_specification():
    fc, series = _picker_fixture()
    cases = [
        (["output_type"], {"output_type": ["B"]}, 1),
        (["output_type", "line"], {"output_type": ["B"]}, 2),
        (["output_type"], {"output_type": ["B", "F"]}, 2),
        (["output_type", "line"], {"output_type": ["B", "F"]}, 4),
        ([], None, 1),                       # nothing selected: 1 combined row
    ]
    for dims, filters, expected in cases:
        out = aggregate_forecasts(fc, series, group_dims=dims, filters=filters)
        assert len(out) == expected, (dims, filters, len(out))


def test_aggregation_is_associative_and_order_independent():
    fc, series = _picker_fixture()
    shuffled = fc.sample(frac=1.0, random_state=7)
    a = aggregate_forecasts(fc, series, group_dims=[])
    b = aggregate_forecasts(shuffled, series, group_dims=[])
    assert a.iloc[0]["demand"] == pytest.approx(b.iloc[0]["demand"])
    # associativity: combining {A,B} with {C,D} equals combining all four
    ab = aggregate_forecasts(fc.iloc[:2], series, group_dims=[])
    cd = aggregate_forecasts(fc.iloc[2:], series, group_dims=[])
    assert (ab.iloc[0]["demand"] + cd.iloc[0]["demand"]) == \
        pytest.approx(a.iloc[0]["demand"])
