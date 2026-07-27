"""Trap 2 — Driver-weighted time averaging.

The averaging family (Mean, MA, WMA) must weight each period's rate by that
period's driver. The fixture uses wildly unequal drivers so the naive
arithmetic mean gives a VISIBLY different answer — otherwise the test proves
nothing.
"""
import numpy as np
import pytest

from core.models.averaging import MovingAverage, WeightedMovingAverage
from core.models.baselines import Mean

# Two periods: driver 10 vs 1000, same consumption 10.
# rates = [1.0, 0.01]; arithmetic mean = 0.505; true ΣC/ΣP = 20/1010 ≈ 0.0198.
DRIVER = np.array([10.0, 1000.0])
CONSUMPTION = np.array([10.0, 10.0])
RATES = CONSUMPTION / DRIVER
TRUE_WEIGHTED = CONSUMPTION.sum() / DRIVER.sum()
ARITHMETIC = RATES.mean()


def test_fixture_makes_the_difference_visible():
    assert ARITHMETIC > 20 * TRUE_WEIGHTED  # 0.505 vs 0.0198


def test_mean_weighted_equals_sum_c_over_sum_p():
    m = Mean().fit(RATES, driver=DRIVER)
    level = m.predict(1)[0]
    assert level == pytest.approx(TRUE_WEIGHTED)
    assert abs(level - ARITHMETIC) > 0.4


def test_moving_average_weighted_equals_sum_c_over_sum_p():
    driver = np.array([500.0, 10.0, 1000.0])
    consumption = np.array([5.0, 10.0, 10.0])
    rates = consumption / driver
    m = MovingAverage(2).fit(rates, driver=driver)
    # window = last 2 periods
    expected = consumption[-2:].sum() / driver[-2:].sum()
    assert m.predict(1)[0] == pytest.approx(expected)
    assert m.predict(1)[0] != pytest.approx(rates[-2:].mean())


def test_wma_applies_recency_on_top_of_driver_weights():
    driver = np.array([700.0, 10.0, 1000.0])
    consumption = np.array([7.0, 10.0, 10.0])
    rates = consumption / driver
    m = WeightedMovingAverage(2).fit(rates, driver=driver)
    w = np.array([1.0, 2.0])  # linear recency over the window, oldest → newest
    expected = np.sum(w * rates[-2:] * driver[-2:]) / np.sum(w * driver[-2:])
    assert m.predict(1)[0] == pytest.approx(expected)
    assert m.predict(1)[0] != pytest.approx(rates[-2:].mean())


def test_without_driver_falls_back_to_plain_averages():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    assert Mean().fit(y).predict(1)[0] == pytest.approx(2.5)
    assert MovingAverage(2).fit(y).predict(1)[0] == pytest.approx(3.5)
