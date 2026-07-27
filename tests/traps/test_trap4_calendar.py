"""Trap 4 — Calendar normalization.

A synthetic Absolute series with exactly constant PER-DAY demand must yield a
flat per-day forecast, and monthly totals that differ purely by month length.
Without normalization the model reports false seasonality (Feb reads as a
~10% demand drop).
"""
import numpy as np
import pandas as pd
import pytest

from core.config import EngineConfig
from core.forecast.generate import generate
from core.forecast.reconstruct import reconstruct
from core.io.schema import build_raw_tables
from core.models.baselines import Mean
from core.prep.calendar import parse_period
from core.prep.series_builder import build_series

CFG = EngineConfig()
PER_DAY = 3.0


def _constant_per_day_workbook():
    """Jan 2024 – Dec 2025: qty = 3.0 × days in month, exactly."""
    dates = pd.date_range("2024-01-01", "2025-12-01", freq="MS")
    cons = pd.DataFrame({
        "date": dates,
        "item_code": "A1",
        "cons_qty_base_uom": [PER_DAY * d.days_in_month for d in dates],
        "cons_qty_ton": 0.0, "cons_$": 0.0,
        "output_type": "x", "production_line": "a",
        "cons_rate": None, "cons_rate_uom": None,
    })
    bom = pd.DataFrame([{
        "item_code": "A1", "item_description": "w", "uom": "p",
        "unit_price_$": 1.0, "unit_wt_kg": 0.1, "category_level1": "c",
        "category_level2": "c", "category_level3": "c"}])
    return build_raw_tables({"bom": bom, "consumption": cons})


def test_raw_monthly_totals_do_vary_but_per_day_target_is_flat():
    prep = build_series(_constant_per_day_workbook(), CFG)
    obs = prep.observations
    assert obs["qty_base"].std() > 0            # unnormalized totals vary…
    assert np.allclose(obs["target"], PER_DAY)  # …the per-day target does not


def test_flat_per_day_forecast_and_month_length_only_variation():
    prep = build_series(_constant_per_day_workbook(), CFG)
    y = prep.observations["target"].to_numpy(dtype=float)
    model = Mean().fit(y)
    fc = generate(model, parse_period("2025-12", CFG.granularity), CFG,
                  confidence=0.9)
    assert np.allclose(fc["target_value"], PER_DAY)  # flat per-day forecast

    fc = reconstruct(fc, "absolute", "a", "x", plan={}, cfg=CFG)
    periods = pd.PeriodIndex(fc["period"], freq="M")
    expected = PER_DAY * periods.days_in_month.to_numpy(dtype=float)
    assert np.allclose(fc["reconstructed_demand"], expected)
    # Feb 2026 (28 days) vs Jan 2026 (31): totals differ by month length only
    jan = fc.loc[fc["period"] == "2026-01", "reconstructed_demand"].iloc[0]
    feb = fc.loc[fc["period"] == "2026-02", "reconstructed_demand"].iloc[0]
    assert jan / feb == pytest.approx(31 / 28)


def test_no_false_seasonality_in_the_normalized_target():
    """The unnormalized series has CV > 0 purely from month lengths; the
    normalized target must show zero variation — no fake seasonal signal."""
    prep = build_series(_constant_per_day_workbook(), CFG)
    obs = prep.observations
    assert obs["qty_base"].std() / obs["qty_base"].mean() > 0.01
    assert obs["target"].std() == pytest.approx(0.0)
