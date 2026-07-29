"""What the tooltip says when a planner hovers a forecast point.

The 80% and 95% bands are drawn as invisible fill traces, so they are skipped
on hover — which left the ranges visible on the chart but unreadable as
numbers. They now ride along on the forecast point itself.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.components import charts


def _history(n=2):
    return pd.DataFrame({"period": [f"2025-{i + 1:02d}" for i in range(n)],
                         "value": [0.0041, 0.0052][:n]})


def _forecast(with_bands=True):
    fc = pd.DataFrame({"period": ["2026-01", "2026-02"],
                       "value": [0.004739, 0.005528]})
    if with_bands:
        fc["lower_80"] = [0.003332, 0.004314]
        fc["upper_80"] = [0.006213, 0.006815]
        fc["lower_95"] = [0.002849, 0.003908]
        fc["upper_95"] = [0.006992, 0.007496]
    return fc


def _trace(fig, name):
    return next(t for t in fig.data if t.name == name)


def test_the_forecast_tooltip_names_both_ranges():
    fig = charts.series_chart(_history(), _forecast(), "value", "value")
    template = _trace(fig, "forecast").hovertemplate

    assert "80% range" in template
    assert "95% range" in template
    assert "customdata[0]" in template and "customdata[3]" in template


def test_the_bounds_travel_with_the_point_in_the_right_order():
    """customdata is positional — the wrong order silently swaps a lower
    bound for an upper one in the tooltip."""
    forecast = _forecast()
    fig = charts.series_chart(_history(), forecast, "value", "value")
    data = _trace(fig, "forecast").customdata

    assert data.shape == (2, 4)
    for row, (_, period) in zip(data, forecast.iterrows()):
        lower_80, upper_80, lower_95, upper_95 = row
        assert lower_95 <= lower_80 <= upper_80 <= upper_95
    assert list(data[0]) == pytest.approx(
        [forecast.loc[0, c] for c in charts.BAND_COLUMNS])


def test_the_invisible_band_traces_stay_out_of_the_tooltip():
    """Four unnamed numbers in a tooltip is worse than none."""
    fig = charts.series_chart(_history(), _forecast(), "value", "value")
    for trace in fig.data:
        if trace.name in ("80% band", "95% band"):
            assert trace.hoverinfo == "skip"


def test_a_forecast_without_bands_still_has_a_readable_tooltip():
    fig = charts.series_chart(_history(), _forecast(with_bands=False),
                              "value", "value")
    trace = _trace(fig, "forecast")

    assert trace.customdata is None
    assert "customdata" not in trace.hovertemplate
    assert "forecast" in trace.hovertemplate


def test_history_and_production_are_labelled_too():
    fig = charts.series_chart(
        _history(), _forecast(), "value", "value",
        driver=pd.DataFrame({"period": ["2025-01", "2025-02"],
                             "driver_qty": [12.5, 14.1]}))

    assert "history" in _trace(fig, "history").hovertemplate
    assert "production" in _trace(fig, "driver").hovertemplate


def test_the_number_format_suits_a_rate_and_a_quantity_alike():
    """A combined demand runs to thousands while a rate is a few
    thousandths; one fixed decimal count cannot serve both, so the format is
    significant-digit based."""
    assert "~g" in charts._NUM
    for template in (charts._FORECAST_HOVER, charts._HISTORY_HOVER,
                     charts._DRIVER_HOVER, charts._FORECAST_HOVER_WITH_BANDS):
        assert charts._NUM in template


def test_the_trace_box_is_suppressed_so_the_tooltip_reads_as_one_note():
    fig = charts.series_chart(_history(), _forecast(), "value", "value")
    assert _trace(fig, "forecast").hovertemplate.endswith("<extra></extra>")
    assert fig.layout.hovermode == "x unified"
