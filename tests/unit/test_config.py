import pytest
from pydantic import ValidationError

from core.config import (
    PERIOD_FREQ,
    SEASONAL_PERIODS,
    EngineConfig,
    ForecastConfig,
    Granularity,
    ModelConfig,
)


def test_defaults():
    cfg = EngineConfig()
    assert cfg.granularity is Granularity.MONTHLY
    assert cfg.seasonal_period == 12
    assert cfg.gate.min_history_competition == 6
    assert cfg.gate.seasonal_min_history == 24
    assert cfg.driver.floor_fraction == 0.20
    assert cfg.models.enable_arima is False
    assert cfg.forecast.interval_levels == (0.80, 0.95)


def test_seasonal_period_derived_from_granularity():
    assert EngineConfig(granularity="weekly").seasonal_period == 52
    assert EngineConfig(granularity="daily").seasonal_period == 7
    assert set(SEASONAL_PERIODS) == set(PERIOD_FREQ) == set(Granularity)


def test_no_coverage_threshold_exists():
    """Mode is permanent: there must be no driver-coverage threshold anywhere
    in the configuration (see docs/decisions.md)."""
    def field_names(model_cls):
        names = set()
        for name, f in model_cls.model_fields.items():
            names.add(name)
            ann = f.annotation
            if hasattr(ann, "model_fields"):
                names |= field_names(ann)
        return names

    names = field_names(EngineConfig)
    assert not any("coverage" in n.lower() for n in names)


def test_invalid_interval_levels_rejected():
    with pytest.raises(ValidationError):
        ForecastConfig(interval_levels=(0.95, 0.80))


def test_lookback_windows_sorted_and_validated():
    assert ModelConfig(lookback_windows=[12, 3, 6, 3]).lookback_windows == [3, 6, 12]
    with pytest.raises(ValidationError):
        ModelConfig(lookback_windows=[1, 3])


def test_config_round_trips_json():
    cfg = EngineConfig(granularity="weekly", fast_mode=True)
    again = EngineConfig.model_validate_json(cfg.model_dump_json())
    assert again == cfg
