"""Fixtures shared by the source-side and exe-side parity tests."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "sample_public.xlsx"

#: CI sets this to the built binary; without it the exe-side tests skip
EXE_ENV = "FORECASTLENS_EXE"
#: keep the parity run small — the assertions are about identity, not scale
HORIZON = "3"


def exe_path() -> Path | None:
    raw = os.environ.get(EXE_ENV)
    if not raw:
        return None
    path = Path(raw)
    return path if path.exists() else None


@pytest.fixture(scope="session")
def source_run(tmp_path_factory):
    """A full run performed by the source version, in-process."""
    from core.config import EngineConfig
    from core.pipeline import run_forecast

    workdir = tmp_path_factory.mktemp("parity_source")
    db = workdir / "results.db"
    cfg = EngineConfig(forecast={"horizon": int(HORIZON)})
    run_id = run_forecast(FIXTURE, cfg, db_path=db, run_name="parity-source")
    return {"db": db, "run_id": run_id, "dir": workdir}


@pytest.fixture(scope="session")
def exe_run(tmp_path_factory):
    """The same run performed by the frozen binary, via its headless mode."""
    binary = exe_path()
    if binary is None:
        pytest.skip(f"{EXE_ENV} not set — build the exe to run parity tests")

    workdir = tmp_path_factory.mktemp("parity_exe")
    db = workdir / "results.db"
    env = dict(os.environ)
    # the frozen app must write to a user-writable place, never its bundle
    env["FORECASTLENS_DATA_DIR"] = str(workdir / "userdata")

    completed = subprocess.run(
        [str(binary), "--run-forecast", "--input", str(FIXTURE),
         "--db", str(db), "--horizon", HORIZON, "--name", "parity-exe"],
        capture_output=True, text=True, timeout=3600, env=env,
        cwd=str(workdir))          # a foreign cwd, exactly like a double-click
    assert completed.returncode == 0, (
        f"the packaged binary failed:\nSTDOUT\n{completed.stdout[-4000:]}\n"
        f"STDERR\n{completed.stderr[-4000:]}")
    run_id = completed.stdout.strip().splitlines()[-1].strip()
    assert run_id, f"no run id printed:\n{completed.stdout[-2000:]}"
    return {"db": db, "run_id": run_id, "dir": workdir, "binary": binary,
            "env": env, "stdout": completed.stdout, "stderr": completed.stderr}
