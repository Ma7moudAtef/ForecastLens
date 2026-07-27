"""Period calendar helpers. Granularity-agnostic — never hardcode monthly.

Absolute-mode targets are normalized to per-day using these day counts; a
28-day February must never read as a demand drop.
"""
from __future__ import annotations

import pandas as pd

from core.config import PERIOD_FREQ, Granularity


def to_period_index(dates: pd.Series, granularity: Granularity) -> pd.PeriodIndex:
    return pd.PeriodIndex(pd.DatetimeIndex(dates), freq=PERIOD_FREQ[granularity])


def days_in_period(periods: pd.PeriodIndex) -> pd.Index:
    """Calendar days covered by each period (29 for Feb 2024, 7 for a week…)."""
    starts = periods.start_time.normalize()
    ends = periods.end_time.normalize()
    return (ends - starts).days + 1


def full_range(first: pd.Period, last: pd.Period) -> pd.PeriodIndex:
    return pd.period_range(first, last, freq=first.freq)


def period_str(p: pd.Period) -> str:
    return str(p)


def parse_period(s: str, granularity: Granularity) -> pd.Period:
    return pd.Period(s, freq=PERIOD_FREQ[granularity])
