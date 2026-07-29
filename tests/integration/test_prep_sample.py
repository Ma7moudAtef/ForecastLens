"""M2 integration: series construction reproduces the reference facts."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.config import EngineConfig
from core.io.excel_source import ExcelSource
from core.prep.series_builder import build_series

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_public.xlsx"


@pytest.fixture(scope="module")
def prep():
    raw = ExcelSource(FIXTURE).load()
    return build_series(raw, EngineConfig())


def test_820_series(prep):
    assert len(prep.series) == 820
    assert prep.series["series_id"].is_unique


def test_item_mode_split_122_absolute_126_relative(prep):
    """code136 is the 122nd Absolute item: its only series is the orphan,
    whose rate has no denominator anywhere, so its quantity is forecast
    directly."""
    per_item = prep.series.groupby("item_code")["mode"].nunique()
    assert (per_item == 1).all()  # zero items mix modes
    item_mode = prep.series.groupby("item_code")["mode"].first()
    assert (item_mode == "absolute").sum() == 122
    assert (item_mode == "relative").sum() == 126


def test_exactly_one_orphan(prep):
    """(code136, a, C) carries a rate but output C never appears on line a in
    the driver sheet. The denominator does not exist, so the quantity is
    forecast directly — and the series is still flagged, because a planner
    who supplied a rate needs to know it was set aside."""
    orphans = prep.series[prep.series["is_orphan"] == 1]
    assert len(orphans) == 1
    assert orphans.iloc[0]["series_id"] == "code136|a|C"
    assert orphans.iloc[0]["mode"] == "absolute"
    assert orphans.iloc[0]["mode_source"] == "no_driver"
    assert orphans.iloc[0]["n_reliable"] > 0


def test_a_missing_driver_period_never_changes_a_mode(prep):
    """The orphan rule is about a combination with no driver in ANY period.
    A run of missing periods inside an otherwise-driven series is an ordinary
    data gap and must leave the mode alone."""
    rated = prep.series[prep.series["mode"] == "relative"]
    assert (rated["mode_source"] != "no_driver").all()
    assert (prep.series["mode_source"] == "no_driver").sum() == 1


def test_history_length_reference_facts(prep):
    s = prep.series
    assert s["n_observed"].median() == 17
    assert (s["n_observed"] < 6).sum() == 304
    assert (s["n_observed"] >= 24).sum() == 356
    assert (s["n_periods"] < 6).sum() == 194      # span-based (classification)


def test_driver_aggregation(prep):
    agg = prep.driver_agg
    act = agg[agg["driver_type"] == "actual"]
    plan = agg[agg["driver_type"] == "plan"]
    assert act["period"].nunique() == 30           # monthly actuals
    assert plan["period"].nunique() == 18          # 549 daily rows → 18 months
    assert str(plan["period"].min()) == "2026-07"
    assert str(plan["period"].max()) == "2027-12"
    assert not plan["is_partial"].any()            # plan covers whole months
    assert set(act["output_type"]) == {"x", "y"}   # no C anywhere in driver


def test_absolute_targets_calendar_normalized(prep):
    obs = prep.observations.merge(
        prep.series[["series_id", "mode"]], on="series_id")
    ab = obs[(obs["mode"] == "absolute") & (obs["is_gap_filled"] == 0)]
    days = pd.PeriodIndex(ab["period"], freq="M").days_in_month
    assert np.allclose(ab["target"] * days, ab["qty_base"])


def test_gap_filling_produces_continuous_index(prep):
    counts = prep.observations.groupby("series_id").size()
    spans = prep.series.set_index("series_id")["n_periods"]
    assert (counts == spans.reindex(counts.index)).all()


def test_low_driver_warnings_present(prep):
    low = [w for w in prep.warnings if w.code == "LOW_DRIVER_PERIODS"]
    assert len(low) > 0  # driver CV≈0.97 with near-zero periods guarantees these
