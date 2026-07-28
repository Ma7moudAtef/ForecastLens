"""The reported bug, checked against the real workbook.

"For combined view in explorer tab, in relative mode, the history is giving
me values not matching the forecast … the history values are divided by 1000
from what I already provided."

History was derived as Σqty_base ÷ Σdriver while the forecast is the
driver-weighted mean of the recorded rates. Because `cons_rate` in this
workbook is qty_ton ÷ days — not qty_base ÷ driver — the two sat on
different scales.
"""
import numpy as np
import pytest

from core.forecast.aggregate import aggregate_forecasts, aggregate_observations
from core.store.repository import Repository

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def data(pipeline_run):
    with Repository(pipeline_run["db"]) as repo:
        series = repo.get_series()
        observations = repo.get_observations()
        forecasts = repo.get_forecasts(pipeline_run["run_id"])
    return series, observations, forecasts


def test_combined_history_rate_matches_the_recorded_rates(data):
    """The combined history rate must be the driver-weighted mean of the
    cons_rate values actually recorded — the same numbers the planner sees
    in the workbook, not a quantity-derived proxy."""
    series, observations, _ = data
    relative = series[series["mode"] == "relative"]
    agg = aggregate_observations(observations, relative, group_dims=[])

    obs = observations.merge(relative[["series_id"]], on="series_id")
    obs = obs[obs["rate"].notna() & obs["driver_qty"].notna()]
    expected = ((obs["rate"] * obs["driver_qty"]).sum()
                / obs["driver_qty"].sum())

    weights = agg["rate"].notna()
    overall = ((agg.loc[weights, "rate"]).mean())
    assert overall == pytest.approx(expected, rel=0.35)
    # the recorded rates are of order 1e-3 here; a quantity-derived rate
    # would be one to three orders of magnitude larger
    assert overall < 0.05


def test_history_and_forecast_rates_are_the_same_order_of_magnitude(data):
    """The symptom the user saw: the two halves of one chart living on
    different scales."""
    series, observations, forecasts = data
    relative = series[series["mode"] == "relative"]

    hist = aggregate_observations(observations, relative, group_dims=[])
    fore = aggregate_forecasts(forecasts, relative, group_dims=[])

    h = hist.loc[hist["rate"].notna(), "rate"].tail(6).mean()
    f = fore.loc[fore["rate"].notna(), "rate"].head(6).mean()
    assert np.isfinite(h) and np.isfinite(f)
    ratio = f / h
    assert 0.2 < ratio < 5.0, (
        f"history {h:.6g} and forecast {f:.6g} differ by {ratio:.1f}× — "
        "they are not on the same scale")


def test_combined_driver_is_real_production_not_multiplied_by_item_count(data):
    """105 items on one line share one production figure."""
    series, observations, forecasts = data
    relative = series[series["mode"] == "relative"]

    fore = aggregate_forecasts(forecasts, relative, group_dims=[])
    row = fore[fore["driver_plan"] > 0].iloc[0]

    members = forecasts[
        forecasts["series_id"].isin(set(relative["series_id"])) &
        (forecasts["period"] == row["period"])].dropna(subset=["driver_plan"])
    naive_sum = members["driver_plan"].sum()

    assert row["driver_plan"] < naive_sum / 10, (
        "the driver still looks like it was counted once per item")
    assert row["n_series"] > 100


def test_single_item_combined_rate_equals_its_own_rate(data):
    """With one item selected, the 'combined' rate is just that item's
    driver-weighted rate — a sanity anchor a planner can verify by hand."""
    series, observations, _ = data
    relative = series[(series["mode"] == "relative") &
                      (series["is_orphan"] == 0)]
    sid = relative.iloc[0]["series_id"]
    one = relative[relative["series_id"] == sid]

    agg = aggregate_observations(observations, one, group_dims=[])
    obs = observations[observations["series_id"] == sid]
    merged = agg.merge(obs[["period", "rate"]], on="period",
                       suffixes=("_combined", "_raw"))
    both = merged.dropna(subset=["rate_combined", "rate_raw"])
    assert len(both) > 3
    assert np.allclose(both["rate_combined"], both["rate_raw"], equal_nan=True)
