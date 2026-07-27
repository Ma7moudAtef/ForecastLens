import numpy as np
import pytest

from core.selection import metrics as M


def test_mae_rmse_basic():
    a = np.array([1.0, 2.0, 3.0])
    f = np.array([1.0, 1.0, 5.0])
    assert M.mae(a, f) == pytest.approx(1.0)
    assert M.rmse(a, f) == pytest.approx(np.sqrt(5 / 3))


def test_mape_excludes_zero_actuals_and_none_when_all_zero():
    a = np.array([0.0, 10.0])
    f = np.array([5.0, 11.0])
    assert M.mape(a, f) == pytest.approx(10.0)   # only the non-zero actual
    assert M.mape(np.zeros(3), np.ones(3)) is None


def test_smape_defined_with_zeros_present():
    a = np.array([0.0, 10.0])
    f = np.array([0.0, 10.0])
    assert M.smape(a, f) == pytest.approx(0.0)


def test_mase_survives_zeros_and_small_scales():
    """MASE must stay meaningful where MAPE is unusable: tiny rates and
    zero-heavy series."""
    train = np.array([0.003, 0.0, 0.004, 0.0, 0.003, 0.004])
    actual = np.array([0.003, 0.0])
    good = np.array([0.003, 0.0005])
    bad = np.array([0.03, 0.02])
    assert M.mase(actual, good, train) < M.mase(actual, bad, train)


def test_mase_scale_free():
    train = np.array([10.0, 12, 11, 13, 12])
    actual, fc = np.array([12.0, 13]), np.array([11.0, 12])
    small = M.mase(actual / 1000, fc / 1000, train / 1000)
    assert M.mase(actual, fc, train) == pytest.approx(small)


def test_mase_constant_train_degenerate_cases():
    train = np.ones(6)
    assert M.mase(np.ones(2), np.ones(2), train) == 0.0
    assert M.mase(np.ones(2), np.zeros(2), train) == float("inf")
