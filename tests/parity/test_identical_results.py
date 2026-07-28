"""The check that matters: the exe and the source produce the same numbers.

A packaged build that runs perfectly but forecasts differently is worse than
one that fails outright, because nobody notices. This compares every
forecast value, interval bound, reconstructed demand, confidence and model
choice between the two.
"""
import pytest

from tests.parity import assertions as A

pytestmark = pytest.mark.slow


def test_forecasts_are_identical(source_run, exe_run):
    source = A.forecast_fingerprint(source_run["db"], source_run["run_id"])
    frozen = A.forecast_fingerprint(exe_run["db"], exe_run["run_id"])
    A.assert_identical_forecasts(source, frozen, "source", "exe")


def test_model_choices_are_identical(source_run, exe_run):
    from core.store.repository import Repository

    def chosen(db, run_id):
        with Repository(db) as repo:
            sel = repo.get_selections(run_id)
        return (sel[["series_id", "model_name", "window", "route",
                     "reason_code", "confidence_label"]]
                .sort_values("series_id").reset_index(drop=True))

    source = chosen(source_run["db"], source_run["run_id"])
    frozen = chosen(exe_run["db"], exe_run["run_id"])
    differences = source.compare(frozen) if source.shape == frozen.shape else None
    assert differences is not None and differences.empty, (
        "the packaged build chose different models:\n"
        f"{differences if differences is not None else 'shape mismatch'}")


def test_series_metadata_is_identical(source_run, exe_run):
    from core.store.repository import Repository

    def profile(db):
        with Repository(db) as repo:
            series = repo.get_series()
        return (series[["series_id", "mode", "mode_source", "pattern_class",
                        "n_periods", "n_observed", "n_reliable", "is_orphan"]]
                .sort_values("series_id").reset_index(drop=True))

    source = profile(source_run["db"])
    frozen = profile(exe_run["db"])
    assert source.equals(frozen), (
        "the packaged build classified series differently:\n"
        f"{source.compare(frozen) if source.shape == frozen.shape else 'shape mismatch'}")
