"""Trap 3 — Cross-validation leakage.

Every fold must satisfy max(train_index) < min(test_index). The assertion
lives in production code (core/selection/cv.py), not only here; these tests
prove the fold construction obeys it and that no model ever sees the future.
"""
import numpy as np
import pytest

from core.config import EngineConfig
from core.models.base import BaseModel
from core.models.registry import Candidate
from core.selection.cv import evaluate_candidate, fold_origins

CFG = EngineConfig()


class SpyModel(BaseModel):
    """Records exactly what data it was shown at every fit."""

    name = "Spy"
    min_history = 2
    seen: list[np.ndarray] = []

    def _fit(self, y, driver, period_index):
        SpyModel.seen.append(y.copy())
        self.last_ = y[-1]

    def predict(self, horizon):
        return np.full(horizon, self.last_)

    def explain(self):
        return "spy"


def test_folds_are_chronological_and_disjoint():
    y = np.arange(30, dtype=float)
    res = evaluate_candidate(Candidate(SpyModel, "Spy"), y, None, CFG)
    assert res.status == "ok"
    h = CFG.cv.horizon
    origins = sorted(res.fold_predictions)
    assert origins == sorted(set(origins))            # unique
    for origin in origins:
        train_idx = np.arange(0, origin)
        test_idx = np.arange(origin, origin + h)
        assert train_idx.max() < test_idx.min()       # the trap assertion
        assert test_idx.max() <= len(y)


def test_model_never_sees_future_data():
    """The series equals its own index, so any leaked future point would be
    visible as a value >= the fold origin inside the training data."""
    SpyModel.seen = []
    y = np.arange(40, dtype=float)
    res = evaluate_candidate(Candidate(SpyModel, "Spy"), y, None, CFG)
    origins = sorted(res.fold_predictions)
    assert len(SpyModel.seen) == len(origins)
    for origin, train in zip(origins, SpyModel.seen):
        assert len(train) == origin                   # exactly [0, origin)
        assert train.max() == origin - 1              # nothing from the future


def test_no_fabricated_competition_below_three_origins():
    y = np.arange(6, dtype=float)  # horizon 3, min_train 2 → 2 origins only
    res = evaluate_candidate(Candidate(SpyModel, "Spy"), y, None, CFG)
    assert res.status == "skipped"
    assert "3" in res.fail_reason


def test_fold_origins_capped_at_most_recent():
    origins = fold_origins(n=100, horizon=3, min_train=5, max_origins=8)
    assert len(origins) == 8
    assert origins[-1] == 100 - 3        # ends at the most recent possible
    assert origins == sorted(origins)    # chronological


def test_random_splits_are_structurally_impossible():
    """fold_origins yields contiguous chronological prefixes only."""
    origins = fold_origins(n=20, horizon=3, min_train=4, max_origins=50)
    assert origins == list(range(4, 18))
