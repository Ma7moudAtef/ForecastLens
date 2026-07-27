"""Synthetic known-answer tests: every model against a series whose right
answer is known in advance."""
import numpy as np
import pytest

from core.models.anchors import CategoryPrior, StandardRateAnchor
from core.models.averaging import MovingAverage, WeightedMovingAverage
from core.models.baselines import Drift, Mean, Naive, SeasonalNaive
from core.models.ensemble import Ensemble
from core.models.intermittent import SBA, TSB, Croston, ZeroForecast
from core.models.smoothing import ETS, SES, DampedHolt, Holt, HoltWinters
from core.models.statistical import ARIMA, Theta

RNG = np.random.default_rng(42)


def test_naive_repeats_last_value():
    m = Naive().fit(np.array([1.0, 5.0, 3.0]))
    assert list(m.predict(3)) == [3.0, 3.0, 3.0]


def test_seasonal_naive_repeats_last_cycle():
    season = np.array([10.0, 20, 30, 40], dtype=float)
    y = np.tile(season, 3)
    m = SeasonalNaive(4).fit(y)
    assert list(m.predict(6)) == [10.0, 20, 30, 40, 10, 20]


def test_drift_extends_the_line():
    y = 2.0 * np.arange(10) + 5.0
    m = Drift().fit(y)
    assert np.allclose(m.predict(3), [25.0, 27.0, 29.0])


def test_mean_recovers_constant_under_noise():
    y = 50.0 + RNG.normal(0, 1, 40)
    m = Mean().fit(y)
    assert abs(m.predict(1)[0] - 50.0) < 1.0


def test_mean_driver_weighted_equals_sum_c_over_sum_p():
    driver = np.array([10.0, 1000.0])
    consumption = np.array([10.0, 10.0])
    rates = consumption / driver          # [1.0, 0.01]
    m = Mean().fit(rates, driver=driver)
    assert np.isclose(m.predict(1)[0], consumption.sum() / driver.sum())


def test_moving_average_uses_only_the_window():
    y = np.array([100.0, 100, 100, 2, 4, 6])
    m = MovingAverage(3).fit(y)
    assert m.predict(1)[0] == pytest.approx(4.0)


def test_wma_weights_recent_periods_more():
    y = np.array([99.0, 0, 0, 0, 10])   # window sees the last 4 points
    m = WeightedMovingAverage(4).fit(y)
    # linear recency weights 1,2,3,4 → level = 40/10 = 4 > arithmetic mean 2.5
    assert m.predict(1)[0] == pytest.approx(4.0)


def test_ses_flat_on_stable_series():
    y = 5.0 + RNG.normal(0, 0.1, 30)
    m = SES().fit(y)
    f = m.predict(6)
    assert np.allclose(f, f[0])
    assert abs(f[0] - 5.0) < 0.3


def test_holt_recovers_trend_slope():
    y = 3.0 * np.arange(30) + 10.0 + RNG.normal(0, 0.5, 30)
    m = Holt().fit(y)
    f = m.predict(5)
    slopes = np.diff(f)
    assert np.all(np.abs(slopes - 3.0) < 0.5)


def test_damped_holt_flattens_the_trend():
    y = 3.0 * np.arange(30) + 10.0 + RNG.normal(0, 0.5, 30)
    m = DampedHolt().fit(y)
    f = m.predict(24)
    early, late = f[1] - f[0], f[23] - f[22]
    assert late <= early + 1e-9        # damping: slope must not grow
    assert f[23] - f[22] < 3.0         # and must be below the raw trend


def test_holt_winters_captures_seasonality():
    t = np.arange(48)
    y = 100.0 + 20.0 * np.sin(2 * np.pi * t / 12) + RNG.normal(0, 1, 48)
    m = HoltWinters(12).fit(y)
    f = m.predict(12)
    expected = 100.0 + 20.0 * np.sin(2 * np.pi * (t[-1] + 1 + np.arange(12)) / 12)
    assert np.corrcoef(f, expected)[0, 1] > 0.95


def test_ets_picks_nonseasonal_form_on_flat_data():
    y = 10.0 + RNG.normal(0, 0.2, 30)
    m = ETS(12, allow_seasonal=True).fit(y)
    assert m.form_.get("seasonal") is None


def test_ets_finds_seasonality_when_it_exists():
    t = np.arange(48)
    y = 100.0 + 30.0 * np.sin(2 * np.pi * t / 12) + RNG.normal(0, 1, 48)
    m = ETS(12, allow_seasonal=True).fit(y)
    assert m.form_.get("seasonal") is not None


def test_theta_tracks_trend():
    y = 2.0 * np.arange(24) + 5.0 + RNG.normal(0, 0.5, 24)
    m = Theta().fit(y)
    f = m.predict(6)
    assert f[-1] > f[0]                       # follows the direction
    assert abs(f[0] - (2.0 * 24 + 5.0)) < 4.0  # lands near the true line


def test_arima_handles_ar1_structure():
    y = np.zeros(60)
    for i in range(1, 60):
        y[i] = 0.8 * y[i - 1] + RNG.normal(0, 1)
    y += 50.0
    m = ARIMA().fit(y)
    f = m.predict(3)
    assert np.all(np.isfinite(f))
    # AR pull: forecast moves from last value toward the mean
    assert min(y[-1], 50.0) - 3 < f[0] < max(y[-1], 50.0) + 3


def test_croston_estimates_size_and_interval():
    y = np.array([0.0, 6, 0, 0, 6, 0, 0, 6, 0, 0, 6, 0])
    m = Croston(alpha=0.1).fit(y)
    # size ≈ 6, interval ≈ 3 → rate ≈ 2
    assert m.predict(1)[0] == pytest.approx(2.0, rel=0.3)


def test_sba_corrects_crostons_upward_bias():
    y = np.array([0.0, 6, 0, 0, 6, 0, 0, 6, 0, 0, 6, 0])
    croston = Croston(alpha=0.1).fit(y).predict(1)[0]
    sba = SBA(alpha=0.1).fit(y).predict(1)[0]
    assert sba == pytest.approx(croston * (1 - 0.1 / 2))
    assert sba < croston


def test_tsb_decays_toward_zero_on_obsolete_item_and_croston_does_not():
    """The obsolescence trap: an item that stopped moving a year ago."""
    active = np.array([5.0, 0, 5, 0, 5, 0, 5, 0, 5, 0, 5, 5])
    dead = np.zeros(12)
    y = np.concatenate([active, dead])
    tsb_now = TSB().fit(y).predict(1)[0]
    tsb_then = TSB().fit(active).predict(1)[0]
    croston_now = Croston().fit(y).predict(1)[0]
    croston_then = Croston().fit(active).predict(1)[0]
    assert tsb_now < 0.35 * tsb_then          # TSB decayed hard
    assert croston_now >= 0.55 * croston_then  # Croston barely moved


def test_zero_forecast():
    m = ZeroForecast().fit(np.zeros(6))
    assert np.all(m.predict(12) == 0)


def test_standard_rate_anchor_uses_the_engineered_standard():
    m = StandardRateAnchor(0.0042).fit(np.array([0.005, 0.004]))
    assert np.all(m.predict(6) == 0.0042)


def test_category_prior_uses_pooled_value():
    m = CategoryPrior(3.5, category_level=3, n_siblings=14,
                      category_name="fasteners").fit(np.array([3.0]))
    assert np.all(m.predict(4) == 3.5)
    assert "14 similar item" in m.explain()


def test_ensemble_is_the_average_of_members():
    y = np.arange(12, dtype=float)
    a = Naive().fit(y)          # predicts 11
    b = Mean().fit(y)           # predicts 5.5
    e = Ensemble([a, b])
    e.fit(y)
    assert e.predict(2)[0] == pytest.approx((11 + 5.5) / 2)


def test_every_model_reports_an_explanation_sentence():
    y = np.arange(30, dtype=float) + 10
    models = [
        Naive().fit(y), SeasonalNaive(12).fit(np.tile(np.arange(12.0), 3)),
        Drift().fit(y), Mean().fit(y), MovingAverage(3).fit(y),
        WeightedMovingAverage(3).fit(y), SES().fit(y), Holt().fit(y),
        DampedHolt().fit(y), Theta().fit(y),
        SBA().fit(np.array([0.0, 5, 0, 5, 0, 5])),
        TSB().fit(np.array([0.0, 5, 0, 5, 0, 5])),
        Croston().fit(np.array([0.0, 5, 0, 5, 0, 5])),
        ZeroForecast().fit(y), StandardRateAnchor(1.0).fit(y),
        CategoryPrior(1.0, 3, 5, "c").fit(y),
    ]
    for m in models:
        text = m.explain()
        assert isinstance(text, str) and len(text) > 15, m.name


def test_interval_ordering_property():
    y = 10.0 + RNG.normal(0, 1, 30)
    for model in [Naive(), Mean(), SES(), DampedHolt(), Theta()]:
        m = model.fit(y)
        point = m.predict(6)
        l80, u80 = m.prediction_interval(6, 0.80)
        l95, u95 = m.prediction_interval(6, 0.95)
        assert np.all(l95 <= l80 + 1e-12)
        assert np.all(l80 <= point + 1e-12)
        assert np.all(point <= u80 + 1e-12)
        assert np.all(u80 <= u95 + 1e-12)


def test_too_short_history_raises():
    with pytest.raises(ValueError):
        Holt().fit(np.arange(3, dtype=float))
    with pytest.raises(ValueError):
        SeasonalNaive(12).fit(np.arange(12, dtype=float))
