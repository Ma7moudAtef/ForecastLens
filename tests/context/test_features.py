"""Deriving the operating context from the driver table."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.config import EngineConfig
from core.context import features as F


def _driver(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["period", "line", "output_type",
                                       "driver_qty", "driver_uom",
                                       "driver_type"])


def _two_units(n=6, second=100.0):
    rows = []
    for i in range(n):
        period = f"2024-{i + 1:02d}"
        rows.append([period, "a", "x", 100.0, "ton", "actual"])
        if i % 2 == 0:
            rows.append([period, "b", "x", second, "ton", "actual"])
    return _driver(rows)


def test_no_driver_table_means_no_context():
    frame = F.derive(pd.DataFrame(), EngineConfig())
    assert frame.has_variance is False
    assert "does not apply" in frame.note
    assert frame.frame.empty


def test_single_combination_is_detected_and_skipped():
    rows = [[f"2024-{i:02d}", "a", "x", 100.0, "ton", "actual"]
            for i in range(1, 7)]
    frame = F.derive(_driver(rows), EngineConfig())
    assert frame.has_variance is False
    assert "single unit and stream" in frame.note


def test_regimes_track_which_combinations_ran():
    frame = F.derive(_two_units(), EngineConfig())
    assert frame.has_variance is True
    assert set(frame.regime_counts) == {"a:x+b:x", "a:x"}
    assert frame.regime_counts["a:x+b:x"] == 6      # 3 periods x 2 rows
    assert frame.regime_at("2024-02", "a", "x") == "a:x"


def test_a_combination_below_its_own_floor_counts_as_idle():
    """A unit ticking over at 1% of its usual output did not really run."""
    rows = []
    for i in range(1, 7):
        rows.append([f"2024-{i:02d}", "a", "x", 100.0, "ton", "actual"])
        rows.append([f"2024-{i:02d}", "b", "x",
                     100.0 if i > 2 else 0.5, "ton", "actual"])
    frame = F.derive(_driver(rows), EngineConfig())
    assert frame.regime_at("2024-01", "a", "x") == "a:x"
    assert frame.regime_at("2024-05", "a", "x") == "a:x+b:x"


def test_own_share_and_system_driver_add_up():
    frame = F.derive(_two_units(), EngineConfig())
    period = frame.frame[frame.frame["period"] == "2024-01"]
    assert period["system_driver"].nunique() == 1
    assert period["system_driver"].iloc[0] == pytest.approx(200.0)
    assert period["own_share"].sum() == pytest.approx(1.0)


def test_entropy_is_zero_when_one_combination_carries_everything():
    assert F._entropy(np.array([1.0])) == 0.0
    assert F._entropy(np.array([0.5, 0.5])) == pytest.approx(np.log(2))
    assert F._entropy(np.array([0.99, 0.01])) < np.log(2)


def test_utilization_uses_actual_history_only():
    """A plan bigger than anything ever achieved must not rescale the past."""
    rows = _two_units().values.tolist()
    rows.append(["2024-07", "a", "x", 10_000.0, "ton", "plan"])
    rows.append(["2024-07", "b", "x", 10_000.0, "ton", "plan"])
    with_plan = F.derive(_driver(rows), EngineConfig())
    without = F.derive(_two_units(), EngineConfig())

    key = ["period", "unit", "stream"]
    a = with_plan.frame[with_plan.frame["driver_type"] == "actual"] \
        .set_index(key)["utilization"]
    b = without.frame.set_index(key)["utilization"]
    assert a.loc[b.index].equals(b)


def test_actual_wins_over_a_plan_for_the_same_period():
    rows = _two_units().values.tolist()
    rows.append(["2024-01", "a", "x", 999.0, "ton", "plan"])
    frame = F.derive(_driver(rows), EngineConfig())
    row = frame.frame[(frame.frame["period"] == "2024-01")
                      & (frame.frame["unit"] == "a")]
    assert len(row) == 1
    assert row["driver_qty"].iloc[0] == pytest.approx(100.0)


# --- the supplied calendar ----------------------------------------------------

def _calendar(rows):
    return pd.DataFrame(rows, columns=["period", "factor_name",
                                       "factor_value", "unit", "stream"])


def test_numeric_calendar_factor_becomes_a_feature():
    cal = _calendar([[f"2024-{i:02d}", "promotion", 1.0 if i % 2 else 0.0,
                      None, None] for i in range(1, 7)])
    frame = F.derive(_two_units(), EngineConfig(), calendar=cal)
    assert frame.calendar_features == ["ctx_promotion"]
    assert "ctx_promotion" in frame.feature_names
    assert set(frame.frame["ctx_promotion"].unique()) == {0.0, 1.0}


def test_text_calendar_factor_becomes_one_indicator_per_value():
    cal = _calendar([[f"2024-{i:02d}", "recipe", "A" if i < 4 else "B",
                      None, None] for i in range(1, 7)])
    frame = F.derive(_two_units(), EngineConfig(), calendar=cal)
    assert set(frame.calendar_features) == {"ctx_recipe_A", "ctx_recipe_B"}
    row = frame.frame[frame.frame["period"] == "2024-01"].iloc[0]
    assert row["ctx_recipe_A"] == 1.0 and row["ctx_recipe_B"] == 0.0


def test_calendar_period_written_as_a_date_still_matches():
    cal = _calendar([["2024-01-15", "promotion", 1.0, None, None]])
    frame = F.derive(_two_units(), EngineConfig(), calendar=cal)
    january = frame.frame[frame.frame["period"] == "2024-01"]
    assert (january["ctx_promotion"] == 1.0).all()


def test_a_discrete_factor_joins_the_regime_label():
    cal = _calendar([[f"2024-{i:02d}", "promotion", 1.0 if i % 2 else 0.0,
                      None, None] for i in range(1, 7)])
    frame = F.derive(_two_units(), EngineConfig(), calendar=cal)
    assert any("promotion=1" in label for label in frame.regime_counts)
    assert any("promotion=0" in label for label in frame.regime_counts)


def test_a_continuous_factor_stays_out_of_the_label():
    """A measurement with a different value every period would make every
    period its own regime, which explains nothing."""
    cal = _calendar([[f"2024-{i:02d}", "temperature", 20.0 + i, None, None]
                     for i in range(1, 7)])
    frame = F.derive(_two_units(), EngineConfig(), calendar=cal)
    assert "ctx_temperature" in frame.calendar_features
    assert all("temperature" not in label for label in frame.regime_counts)


def test_a_unit_scoped_factor_only_lands_on_that_unit():
    cal = _calendar([["2024-01", "campaign", 1.0, "a", None]])
    frame = F.derive(_two_units(), EngineConfig(), calendar=cal)
    january = frame.frame[frame.frame["period"] == "2024-01"]
    for row in january.itertuples():
        assert row.ctx_campaign == (1.0 if row.unit == "a" else 0.0)


# --- plain language -----------------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("idle", "nothing running"),
    ("a:x", "only a (x) running"),
    ("a:x+b:y", "a (x) and b (y) running together"),
    ("other", "other, rarer conditions"),
    ("a:x | promotion=1", "only a (x) running with promotion on"),
    ("a:x | promotion=0", "only a (x) running with promotion off"),
])
def test_regimes_read_like_a_sentence(label, expected):
    assert F.humanize_regime(label) == expected
