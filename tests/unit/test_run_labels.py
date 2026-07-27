"""Run labels must survive SQL NULLs however pandas materializes them.

Regression: a database created before the scope/run_number columns existed
returns NULL for them. Depending on pandas version and column dtype that
arrives as None, pd.NA, or float NaN — and `NaN or ""` yields NaN, because
NaN is truthy, which crashed the run picker with
'float' object has no attribute 'strip'.
"""
import numpy as np
import pandas as pd
import pytest

from app.components.db import _text, run_label

NULLS = [None, np.nan, pd.NA, float("nan")]


@pytest.mark.parametrize("null", NULLS, ids=["None", "np.nan", "pd.NA", "nan"])
def test_text_treats_every_null_flavour_as_empty(null):
    assert _text(null) == ""


def test_text_strips_and_stringifies():
    assert _text("  hello  ") == "hello"
    assert _text(42) == "42"


@pytest.mark.parametrize("null", NULLS, ids=["None", "np.nan", "pd.NA", "nan"])
def test_run_label_handles_null_scope_and_name(null):
    row = pd.DataFrame([{
        "run_id": "abc123", "run_number": 1, "name": null,
        "created_at": "2026-07-27T10:00:00", "scope_note": null,
    }]).itertuples().__next__()
    label = run_label(row)                    # must not raise
    assert label.startswith("Run 1")
    assert "abc123" not in label
    assert "nan" not in label.lower()


def test_run_label_handles_a_float_column_of_nulls():
    """The exact shape of the reported crash: all-NULL TEXT columns read
    back as float64, so every value is NaN."""
    runs = pd.DataFrame([{
        "run_id": "abc123", "run_number": 1, "name": np.nan,
        "created_at": "2026-07-27T10:00:00", "scope_note": np.nan,
    }])
    assert runs["scope_note"].dtype == np.float64
    labels = [run_label(r) for r in runs.itertuples()]
    assert labels == ["Run 1 · 2026-07-27 10:00"]


def test_run_label_handles_missing_run_number():
    row = pd.DataFrame([{
        "run_id": "x", "run_number": np.nan, "name": "legacy",
        "created_at": "2026-07-27T10:00:00", "scope_note": "all items",
    }]).itertuples().__next__()
    assert run_label(row) == "Run — legacy · 2026-07-27 10:00 · all items"


def test_run_label_full_form():
    row = pd.DataFrame([{
        "run_id": "x", "run_number": 3, "name": "monthly refresh",
        "created_at": "2026-07-27T14:02:11", "scope_note": "2 items",
    }]).itertuples().__next__()
    assert run_label(row) == \
        "Run 3 — monthly refresh · 2026-07-27 14:02 · 2 items"
