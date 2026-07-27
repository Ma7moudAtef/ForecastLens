"""Property tests for forecast generation and confidence."""
import numpy as np
import pandas as pd
import pytest

from core.config import EngineConfig
from core.forecast.generate import confidence_label, confidence_score, generate
from core.forecast.reconstruct import reconstruct
from core.models.baselines import Drift
from core.models.smoothing import SES
from core.prep.calendar import parse_period

CFG = EngineConfig()
P = parse_period("2026-06", CFG.granularity)


def test_forecasts_clipped_at_zero():
    """A declining series makes Drift predict below zero; generation clips."""
    y = np.linspace(100, 5, 20)
    model = Drift().fit(y)
    assert model.predict(24).min() < 0          # raw model does go negative
    fc = generate(model, P, EngineConfig(forecast={"horizon": 24}), 0.5)
    assert (fc["target_value"] >= 0).all()
    for col in ["lower_80", "upper_80", "lower_95", "upper_95"]:
        assert (fc[col] >= 0).all()


def test_interval_ordering_survives_clipping():
    y = np.linspace(50, 2, 15)
    fc = generate(Drift().fit(y), P, EngineConfig(forecast={"horizon": 18}), 0.5)
    assert (fc["lower_95"] <= fc["lower_80"] + 1e-12).all()
    assert (fc["lower_80"] <= fc["target_value"] + 1e-12).all()
    assert (fc["target_value"] <= fc["upper_80"] + 1e-12).all()
    assert (fc["upper_80"] <= fc["upper_95"] + 1e-12).all()


def test_confidence_falls_as_history_shortens():
    scores = [confidence_score(0.8, n, 0.7, 0.9, CFG, validation_skipped=False)
              for n in (30, 18, 9, 4)]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > scores[-1] + 0.1


def test_cold_start_capped_at_low():
    s = confidence_score(None, 3, 0.9, 1.0, CFG, validation_skipped=True)
    assert s <= 0.35
    assert confidence_label(s) == "low"


def test_confidence_labels():
    assert confidence_label(0.2) == "low"
    assert confidence_label(0.5) == "medium"
    assert confidence_label(0.9) == "high"


def test_reconstruction_missing_plan_yields_nan_not_a_guess():
    y = 0.5 + np.zeros(12)
    fc = generate(SES().fit(y + np.random.default_rng(1).normal(0, 0.01, 12)),
                  P, CFG, 0.5)
    out = reconstruct(fc, "relative", "a", "C", plan={}, cfg=CFG)
    assert out["reconstructed_demand"].isna().all()   # no denominator invented
    assert out["target_value"].notna().all()          # rate forecast still exists


def test_reconstruction_relative_uses_plan_periods():
    y = np.full(12, 2.0)
    fc = generate(SES().fit(y), P, CFG, 0.5)
    plan = {(p, "a", "x"): 100.0 for p in fc["period"][:6]}
    out = reconstruct(fc, "relative", "a", "x", plan=plan, cfg=CFG)
    assert out["reconstructed_demand"].notna().sum() == 6
    covered = out[out["driver_plan"].notna()]
    assert np.allclose(covered["reconstructed_demand"],
                       covered["target_value"] * 100.0)
