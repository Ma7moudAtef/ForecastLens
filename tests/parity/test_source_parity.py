"""The parity assertions, run against the SOURCE version.

These always run. The exe-side file runs the identical assertions against the
frozen binary, and a third file compares the two.
"""
import pytest

from core.export import export_workbook
from tests.parity import assertions as A

pytestmark = pytest.mark.slow


def test_series_are_built(source_run):
    A.assert_series_built(source_run["db"])


def test_mode_split(source_run):
    A.assert_mode_split(A.assert_series_built(source_run["db"]))


def test_orphan_detected(source_run):
    A.assert_orphans(A.assert_series_built(source_run["db"]))


def test_run_completes(source_run):
    A.assert_run_completed(source_run["db"], source_run["run_id"])


def test_database_round_trip(source_run):
    A.assert_database_round_trip(source_run["db"])


def test_export_written(source_run):
    target = source_run["dir"] / "export_source.xlsx"
    export_workbook(source_run["db"], source_run["run_id"], target)
    A.assert_export_written(target)


def test_fingerprint_is_stable_within_the_source_version(source_run):
    """A sanity anchor for the cross-version comparison: the fingerprint of
    one run must equal itself, so any later difference is a real one."""
    first = A.forecast_fingerprint(source_run["db"], source_run["run_id"])
    second = A.forecast_fingerprint(source_run["db"], source_run["run_id"])
    A.assert_identical_forecasts(first, second, "source", "source (re-read)")
    assert not first.empty
