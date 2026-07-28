"""Models 20–22 in isolation: do they recover what is really there, and do
they refuse when it is not?"""
from __future__ import annotations

import numpy as np
import pytest

from core.context.matrix import ContextWindow
from core.models.context_models import (
    ContextRegression,
    FixedPlusVariable,
    RegimeConditional,
)


def _window(n=30, h=4, names=None, X=None, regimes=None, driver=None,
            system=None, future_X=None, future_regimes=None,
            future_driver=None, future_system=None):
    names = names or []
    X = np.zeros((n, 0)) if X is None else X
    future_X = np.zeros((h, X.shape[1])) if future_X is None else future_X
    regimes = np.array(["solo"] * n, dtype=object) if regimes is None else regimes
    future_regimes = (np.array(["solo"] * h, dtype=object)
                      if future_regimes is None else future_regimes)
    driver = np.ones(n) if driver is None else driver
    system = driver if system is None else system
    future_driver = np.ones(h) if future_driver is None else future_driver
    future_system = future_driver if future_system is None else future_system
    return ContextWindow(
        names=names, X=X, regimes=regimes, driver=driver, system_driver=system,
        future_X=future_X, future_regimes=future_regimes,
        future_driver=future_driver, future_system_driver=future_system)


# --- 20: FixedPlusVariable ----------------------------------------------------

def test_fixed_plus_variable_recovers_a_known_split():
    """Build consumption as 200 standing + 3 per tonne, express it as a rate,
    and the model must read both numbers back off it."""
    rng = np.random.default_rng(11)
    driver = rng.uniform(40, 160, 36)
    rate = 200.0 / driver + 3.0
    future_driver = np.array([50.0, 150.0, 100.0])

    model = FixedPlusVariable(target_is_rate=True)
    model.set_context(_window(n=36, h=3, driver=driver,
                              future_driver=future_driver))
    model.fit(rate)

    assert model.fixed_ == pytest.approx(200.0, rel=0.01)
    assert model.variable_ == pytest.approx(3.0, rel=0.01)
    # and it says the useful thing: the rate is higher when the line crawls
    predicted = model.predict(3)
    assert predicted[0] > predicted[2] > predicted[1]


def test_fixed_plus_variable_explains_itself_in_planner_language():
    rng = np.random.default_rng(12)
    driver = rng.uniform(40, 160, 36)
    model = FixedPlusVariable(target_is_rate=True)
    model.set_context(_window(n=36, h=3, driver=driver))
    model.fit(200.0 / driver + 3.0)

    text = model.explain()
    assert "standing" in text and "scales" in text
    assert "nnls" not in text.lower() and "coefficient" not in text.lower()


def test_fixed_plus_variable_refuses_a_flat_driver():
    """With a constant driver the two components are the same number twice
    over — the model must say so rather than report a made-up split."""
    rng = np.random.default_rng(13)
    driver = np.full(30, 100.0) + rng.normal(0, 0.2, 30)
    model = FixedPlusVariable(target_is_rate=True, min_driver_cv=0.10)
    model.set_context(_window(n=30, driver=driver))

    with pytest.raises(ValueError, match="barely varies"):
        model.fit(5.0 + rng.normal(0, 0.1, 30))


def test_fixed_plus_variable_never_reports_negative_standing_consumption():
    rng = np.random.default_rng(14)
    driver = rng.uniform(40, 160, 36)
    # a rate that FALLS as the driver falls — the opposite shape
    rate = 1.0 + driver / 100.0 + rng.normal(0, 0.02, 36)
    model = FixedPlusVariable(target_is_rate=True)
    model.set_context(_window(n=36, driver=driver))
    model.fit(rate)

    assert model.fixed_ >= 0.0
    assert model.variable_ >= 0.0


def test_fixed_plus_variable_uses_whole_plant_activity_for_absolute_series():
    rng = np.random.default_rng(15)
    system = rng.uniform(50, 200, 36)
    y = 20.0 + 0.5 * system + rng.normal(0, 1.0, 36)

    model = FixedPlusVariable(target_is_rate=False)
    model.set_context(_window(n=36, h=2, system=system,
                              future_system=np.array([100.0, 200.0])))
    model.fit(y)

    assert model.fixed_ == pytest.approx(20.0, rel=0.25)
    assert model.variable_ == pytest.approx(0.5, rel=0.05)
    assert model.predict(2)[1] > model.predict(2)[0]


def test_a_model_that_needs_context_refuses_without_it():
    model = FixedPlusVariable()
    with pytest.raises(ValueError, match="needs operating context"):
        model.fit(np.arange(30, dtype=float))


# --- 21: RegimeConditional ----------------------------------------------------

def _regime_series(levels, n_each=10, noise=0.05, seed=21):
    rng = np.random.default_rng(seed)
    y, regimes = [], []
    for name, level in levels.items():
        y.append(rng.normal(level, level * noise, n_each))
        regimes.extend([name] * n_each)
    return np.concatenate(y), np.array(regimes, dtype=object)


def test_regime_conditional_learns_one_level_per_pattern():
    y, regimes = _regime_series({"solo": 5.0, "shared": 8.0})
    future = np.array(["shared", "solo", "shared"], dtype=object)

    model = RegimeConditional(min_regime_obs=4)
    model.set_context(_window(n=len(y), h=3, regimes=regimes,
                              future_regimes=future))
    model.fit(y)

    assert model.levels_["solo"] == pytest.approx(5.0, rel=0.05)
    assert model.levels_["shared"] == pytest.approx(8.0, rel=0.05)
    predicted = model.predict(3)
    assert predicted[0] == pytest.approx(model.levels_["shared"])
    assert predicted[1] == pytest.approx(model.levels_["solo"])


def test_regime_conditional_falls_back_and_flags_an_unseen_pattern():
    y, regimes = _regime_series({"solo": 5.0, "shared": 8.0})
    future = np.array(["brand_new", "solo"], dtype=object)

    model = RegimeConditional(min_regime_obs=4)
    model.set_context(_window(n=len(y), h=2, regimes=regimes,
                              future_regimes=future))
    model.fit(y)
    predicted = model.predict(2)

    assert predicted[0] == pytest.approx(float(np.mean(y)))
    assert model.unseen_ == 1
    assert "never seen before" in model.explain()


def test_regime_conditional_counts_its_levels_as_parameters():
    y, regimes = _regime_series({"solo": 5.0, "shared": 8.0, "third": 6.0})
    model = RegimeConditional(min_regime_obs=4)
    model.set_context(_window(n=len(y), regimes=regimes))
    model.fit(y)
    assert model.n_params == 3


def test_regime_conditional_refuses_a_single_pattern():
    y, regimes = _regime_series({"solo": 5.0}, n_each=20)
    model = RegimeConditional(min_regime_obs=4)
    model.set_context(_window(n=len(y), regimes=regimes))
    with pytest.raises(ValueError, match="two operating patterns"):
        model.fit(y)


# --- 22: ContextRegression ----------------------------------------------------

def test_context_regression_finds_the_feature_that_matters():
    rng = np.random.default_rng(31)
    n = 40
    n_active = rng.integers(1, 4, n).astype(float)
    noise_feature = rng.normal(0, 1, n)
    y = 2.0 + 1.5 * n_active + rng.normal(0, 0.1, n)
    X = np.column_stack([n_active, noise_feature])
    future = np.column_stack([np.array([1.0, 3.0]), np.zeros(2)])

    model = ContextRegression(observations_per_regressor=8)
    model.set_context(_window(n=n, h=2, names=["n_active", "noise"], X=X,
                              future_X=future))
    model.fit(y)

    assert model.feature_names_ == ["n_active"]
    assert model.r2_ > 0.95
    predicted = model.predict(2)
    assert predicted[1] - predicted[0] == pytest.approx(3.0, rel=0.05)


def test_context_regression_respects_its_regressor_budget():
    """One regressor per eight observations, no matter how many are on
    offer — that is the whole defence against fitting noise."""
    rng = np.random.default_rng(32)
    n = 24                                    # budget: 3
    X = rng.normal(0, 1, (n, 6))
    y = X @ np.array([1.0, 0.9, 0.8, 0.7, 0.6, 0.5]) + rng.normal(0, 0.05, n)

    model = ContextRegression(observations_per_regressor=8)
    model.set_context(_window(n=n, h=2, names=[f"f{i}" for i in range(6)], X=X,
                              future_X=rng.normal(0, 1, (2, 6))))
    model.fit(y)

    assert len(model.feature_names_) <= 3


def test_context_regression_rejects_a_duplicate_regressor():
    rng = np.random.default_rng(33)
    n = 40
    a = rng.normal(0, 1, n)
    almost_a = a + rng.normal(0, 1e-4, n)     # says nothing new
    y = 3.0 + 2.0 * a + rng.normal(0, 0.05, n)
    X = np.column_stack([a, almost_a])

    model = ContextRegression(observations_per_regressor=8, max_vif=5.0)
    model.set_context(_window(n=n, h=2, names=["a", "almost_a"], X=X,
                              future_X=np.zeros((2, 2))))
    model.fit(y)

    # which of the twins wins is arbitrary; taking BOTH is the failure
    assert len(model.feature_names_) == 1
    twin = "almost_a" if model.feature_names_ == ["a"] else "a"
    assert "repeats information" in model.rejected_features_[twin]


def test_context_regression_refuses_when_nothing_helps():
    rng = np.random.default_rng(34)
    n = 40
    X = rng.normal(0, 1, (n, 3))
    y = rng.normal(5.0, 1.0, n)              # unrelated to X

    model = ContextRegression(observations_per_regressor=8)
    model.set_context(_window(n=n, h=2, names=["a", "b", "c"], X=X,
                              future_X=np.zeros((2, 3))))
    with pytest.raises(ValueError, match="improved on a plain average"):
        model.fit(y)


def test_context_regression_explains_features_in_plain_words():
    rng = np.random.default_rng(35)
    n = 40
    n_active = rng.integers(1, 4, n).astype(float)
    y = 2.0 + 1.5 * n_active + rng.normal(0, 0.1, n)

    model = ContextRegression()
    model.set_context(_window(n=n, h=2, names=["n_active"],
                              X=n_active.reshape(-1, 1),
                              future_X=np.ones((2, 1))))
    model.fit(y)

    text = model.explain()
    assert "how many units are running" in text
    assert "n_active" not in text and "R2" not in text


def test_a_supplied_factor_keeps_its_own_name_in_the_explanation():
    from core.models.context_models import feature_words

    assert feature_words("ctx_promotion") == "promotion"
    assert feature_words("ctx_holiday_week") == "holiday week"
    assert feature_words("system_driver") == "how much the whole plant runs"


# --- shared behaviour ---------------------------------------------------------

@pytest.mark.parametrize("factory", [
    lambda: FixedPlusVariable(),
    lambda: RegimeConditional(),
    lambda: ContextRegression(),
])
def test_every_context_model_declares_itself(factory):
    model = factory()
    assert model.uses_context is True
    assert model.name
    assert model.min_history >= 8


def test_a_plan_shorter_than_the_horizon_is_refused_not_extrapolated():
    y, regimes = _regime_series({"solo": 5.0, "shared": 8.0})
    model = RegimeConditional(min_regime_obs=4)
    model.set_context(_window(n=len(y), h=2, regimes=regimes,
                              future_regimes=np.array(["solo", "shared"],
                                                      dtype=object)))
    model.fit(y)
    with pytest.raises(ValueError, match="shorter than the horizon"):
        model.predict(6)
