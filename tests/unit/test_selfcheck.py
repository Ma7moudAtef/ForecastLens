"""Startup self-check: it must catch the real frozen-build failures and say
something a non-technical user can act on."""
import sqlite3

import pytest

from core import selfcheck


def test_all_checks_pass_in_a_healthy_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECASTLENS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("FORECASTLENS_DB", raising=False)
    results = selfcheck.run_checks()
    failures = [r for r in results if not r.ok]
    assert not failures, [r.line() for r in failures]
    assert {r.name for r in results} == {
        "Data folder", "Results database", "Bundled files", "Dependencies"}


def test_report_is_readable_and_states_the_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECASTLENS_DATA_DIR", str(tmp_path))
    ok, text = selfcheck.report()
    assert ok
    assert "ForecastLens" in text          # build stamp on the first line
    assert "Startup checks passed" in text
    assert "Traceback" not in text


def test_unwritable_data_folder_is_reported_with_a_remedy(monkeypatch, tmp_path):
    """The classic frozen failure: the app tries to write where it cannot."""
    def deny() -> None:
        raise PermissionError("read-only file system")

    monkeypatch.setattr(selfcheck.paths, "data_dir",
                        lambda: (_ for _ in ()).throw(PermissionError("denied")))
    result = selfcheck._check_data_dir()
    assert not result.ok
    assert "FORECASTLENS_DATA_DIR" in result.remedy
    assert "Traceback" not in result.line()


def test_unopenable_database_is_reported_with_a_remedy(monkeypatch, tmp_path):
    monkeypatch.setenv("FORECASTLENS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(selfcheck.sqlite3, "connect",
                        lambda *a, **k: (_ for _ in ()).throw(
                            sqlite3.OperationalError("unable to open")))
    result = selfcheck._check_database()
    assert not result.ok
    assert "cannot open" in result.detail
    assert result.remedy


def test_missing_bundled_asset_is_named(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(selfcheck.paths, "bundled_sample", lambda: None)
    monkeypatch.setattr(selfcheck.paths, "schema_sql",
                        lambda: Path("/nonexistent/schema.sql"))
    result = selfcheck._check_assets()
    assert not result.ok
    assert "schema.sql" in result.detail
    assert "sample workbook" in result.detail
    assert "antivirus" in result.remedy      # the usual real-world cause


def test_missing_dependency_is_named_with_its_purpose(monkeypatch):
    import importlib

    real = importlib.import_module

    def fake(name, *args, **kwargs):
        if name == "statsmodels.tsa.holtwinters":
            raise ImportError("No module named 'statsmodels.tsa.holtwinters'")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake)
    result = selfcheck._check_imports()
    assert not result.ok
    assert "statsmodels.tsa.holtwinters" in result.detail
    assert "smoothing forecast models" in result.detail   # what the user loses


def test_a_failing_report_says_the_app_cannot_run(monkeypatch, tmp_path):
    monkeypatch.setattr(selfcheck.paths, "bundled_sample", lambda: None)
    ok, text = selfcheck.report()
    assert not ok
    assert "STARTUP FAILED" in text
    assert "FAIL" in text


def test_a_broken_check_cannot_crash_the_launcher(monkeypatch):
    def explode():
        raise RuntimeError("boom")

    monkeypatch.setattr(selfcheck, "CHECKS", (explode,))
    results = selfcheck.run_checks()
    assert len(results) == 1 and not results[0].ok
    assert "boom" in results[0].detail
