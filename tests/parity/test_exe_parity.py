"""The SAME assertions, run against the frozen binary.

Skipped unless FORECASTENGINE_EXE points at a built binary; CI sets it after
the packaging step, so a build cannot be published without these passing.
"""
import subprocess

import pytest

from tests.parity import assertions as A

pytestmark = pytest.mark.slow


def test_binary_reports_its_build(exe_run):
    out = subprocess.run([str(exe_run["binary"]), "--version"],
                         capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    stamp = out.stdout.strip()
    assert "ForecastEngine" in stamp
    assert "exe" in stamp, f"the binary does not know it is frozen: {stamp}"


def test_startup_self_check_passes(exe_run):
    out = subprocess.run([str(exe_run["binary"]), "--selfcheck"],
                         capture_output=True, text=True, timeout=600,
                         env=exe_run["env"], cwd=str(exe_run["dir"]))
    assert out.returncode == 0, (
        "the packaged app's own startup check failed:\n" + out.stdout[-4000:])
    for check in ("Data folder", "Results database", "Bundled files",
                  "Dependencies"):
        assert check in out.stdout, out.stdout[-2000:]
    assert "FAIL" not in out.stdout, out.stdout[-4000:]


def test_series_are_built(exe_run):
    A.assert_series_built(exe_run["db"])


def test_mode_split(exe_run):
    A.assert_mode_split(A.assert_series_built(exe_run["db"]))


def test_orphan_detected(exe_run):
    A.assert_orphans(A.assert_series_built(exe_run["db"]))


def test_run_completes(exe_run):
    A.assert_run_completed(exe_run["db"], exe_run["run_id"])


def test_database_round_trip(exe_run):
    A.assert_database_round_trip(exe_run["db"])


def test_export_written(exe_run):
    """The binary must be able to export on its own — the export code lives
    in core, so the exe and the web app write the same file."""
    target = exe_run["dir"] / "export_exe.xlsx"
    out = subprocess.run(
        [str(exe_run["binary"]), "--export", "--db", str(exe_run["db"]),
         "--run", exe_run["run_id"], "--out", str(target)],
        capture_output=True, text=True, timeout=1200,
        env=exe_run["env"], cwd=str(exe_run["dir"]))
    assert out.returncode == 0, out.stderr[-4000:]
    A.assert_export_written(target)


def test_nothing_was_written_inside_the_bundle(exe_run):
    """sys._MEIPASS is read-only at runtime: the database, logs and exports
    must all have landed under the user data directory instead."""
    binary_dir = exe_run["binary"].resolve().parent
    strays = [p for p in binary_dir.rglob("*")
              if p.is_file() and p.suffix in {".db", ".sqlite", ".sqlite3"}]
    assert not strays, f"the app wrote a database inside its own bundle: {strays}"
