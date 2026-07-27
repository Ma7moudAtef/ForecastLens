"""Configuration models for the forecast engine.

Everything the pipeline can be told is declared here as pydantic models with
safe defaults. There is deliberately NO driver-coverage threshold: mode is a
property of the material's nature, not of data availability (see
docs/decisions.md). Missing driver periods are ordinary data gaps.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class Granularity(str, Enum):
    MONTHLY = "monthly"
    WEEKLY = "weekly"
    DAILY = "daily"


#: Seasonal cycle length implied by each granularity. Never hardcode 12.
SEASONAL_PERIODS: dict[Granularity, int] = {
    Granularity.MONTHLY: 12,
    Granularity.WEEKLY: 52,
    Granularity.DAILY: 7,
}

#: pandas period frequency alias per granularity.
PERIOD_FREQ: dict[Granularity, str] = {
    Granularity.MONTHLY: "M",
    Granularity.WEEKLY: "W",
    Granularity.DAILY: "D",
}


class GateConfig(BaseModel):
    """History thresholds that decide which models may compete."""

    min_history_competition: int = Field(6, ge=2)
    seasonal_min_history: int = Field(24, ge=8)
    min_cv_origins: int = Field(3, ge=2)


class DriverConfig(BaseModel):
    """Driver (a.k.a. production) handling.

    ``floor_fraction``: a period whose driver quantity falls below this
    fraction of the series' median driver is marked unreliable — rates against
    a near-zero denominator explode. Unreliable periods are excluded from
    fitting and surfaced as warnings.
    """

    floor_fraction: float = Field(0.20, ge=0.0, le=1.0)


class ModelConfig(BaseModel):
    """Model library toggles."""

    enable_arima: bool = False  # gated >=24 periods and off by default
    disabled_models: list[str] = Field(default_factory=list)
    lookback_windows: list[int] = Field(default_factory=lambda: [3, 6, 12])
    ensemble_mase_tolerance: float = Field(0.10, ge=0.0)

    @field_validator("lookback_windows")
    @classmethod
    def _positive_windows(cls, v: list[int]) -> list[int]:
        if any(w < 2 for w in v):
            raise ValueError("lookback windows must be >= 2")
        return sorted(set(v))


class CVConfig(BaseModel):
    """Rolling-origin cross-validation parameters."""

    horizon: int = Field(3, ge=1)
    max_origins: int = Field(8, ge=3)


class SelectionConfig(BaseModel):
    simplicity_mase_tolerance: float = Field(0.05, ge=0.0)


class ForecastConfig(BaseModel):
    horizon: int = Field(12, ge=1)
    interval_levels: tuple[float, float] = (0.80, 0.95)

    @field_validator("interval_levels")
    @classmethod
    def _ordered_levels(cls, v: tuple[float, float]) -> tuple[float, float]:
        lo, hi = v
        if not (0.0 < lo < hi < 1.0):
            raise ValueError("interval levels must satisfy 0 < inner < outer < 1")
        return v


class RunScope(BaseModel):
    """Which materials a run covers.

    Empty `item_codes` means every item. Behaviour analysis always runs over
    the FULL dataset regardless of scope, so category priors keep borrowing
    from all siblings and the data summary stays complete — only model
    selection and forecasting are restricted to the chosen items.
    """

    item_codes: list[str] = Field(default_factory=list)

    def covers_all(self) -> bool:
        return not self.item_codes

    def note(self) -> str:
        if self.covers_all():
            return "all items"
        if len(self.item_codes) == 1:
            return f"1 item ({self.item_codes[0]})"
        return f"{len(self.item_codes)} items"


class EngineConfig(BaseModel):
    """Top-level configuration for one forecast run."""

    granularity: Granularity = Granularity.MONTHLY
    scope: RunScope = Field(default_factory=RunScope)
    gate: GateConfig = Field(default_factory=GateConfig)
    driver: DriverConfig = Field(default_factory=DriverConfig)
    models: ModelConfig = Field(default_factory=ModelConfig)
    cv: CVConfig = Field(default_factory=CVConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    forecast: ForecastConfig = Field(default_factory=ForecastConfig)
    n_jobs: int = Field(-1, description="joblib worker count; -1 = cpu_count - 1")
    random_seed: int = 42
    fast_mode: bool = Field(False, description="skip lookback-window sweeps")

    @property
    def seasonal_period(self) -> int:
        return SEASONAL_PERIODS[self.granularity]

    @property
    def period_freq(self) -> str:
        return PERIOD_FREQ[self.granularity]


class AppConfig(BaseModel):
    """Application-level (non-engine) settings."""

    db_path: Path = Path("forecastlens.db")
    max_upload_mb: int = Field(100, ge=1)
    allowed_upload_extensions: tuple[str, ...] = (".xlsx",)
    shared_secret_env_var: str = "FORECASTLENS_SECRET"
