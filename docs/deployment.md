# Deployment

## 1. From source (macOS / Linux / Windows)

```bash
pip install -r requirements.txt    # or: pip install -e .
streamlit run app/main.py          # UI
python -m cli.run --input data.xlsx --db results.db   # headless batch
```

Every app script bootstraps `sys.path` itself, so `streamlit run app/main.py`
works from a plain clone with no editable install and from any working
directory. (Without that bootstrap, Streamlit puts `app/` — not the project
root — on `sys.path`, and every page dies with
`ModuleNotFoundError: No module named 'app'`.)

## 1b. Streamlit Community Cloud

Point the app at `app/main.py`. Dependencies come from the root
`requirements.txt` — Community Cloud prefers it over `pyproject.toml` (its
same-directory precedence is `uv.lock` → `Pipfile` → `environment.yml` →
`requirements.txt` → `pyproject.toml`). Do not delete `requirements.txt`:
without it the platform treats `pyproject.toml` as a Poetry project and
resolves ALL extras, and the Windows-only `pyinstaller` extra makes that
unsolvable on newer Python runtimes (this exact failure happened; the extra
now carries a `python_version` marker as a second line of defense, and
`tests/unit/test_requirements_sync.py` keeps the two files in sync).

In the deploy dialog's advanced settings, pick **Python 3.11–3.13** — the
versions the engine is tested on. Set `FORECASTLENS_SECRET` in the app's
secrets/environment if you want the shared-secret gate.

**Streamlit floor: 1.51.** The UI uses `st.navigation` for its named tabs
(1.36+) and `width="stretch"` on charts, dataframes and the data editor.
`st.dataframe`/`st.data_editor` accepted `width="stretch"` from 1.49, but
`st.plotly_chart` only from **1.51** — on anything older every chart raises
`TypeError`. `tests/unit/test_requirements_sync.py` fails if the pin in
either dependency file drops below that, or if the installed version does.

Note that Community Cloud storage is ephemeral: the SQLite result store
resets on reboot, so treat cloud deployments as demo/exploration and export
anything you want to keep.

Environment variables:

| Variable | Effect |
|---|---|
| `FORECASTLENS_DB` | SQLite path the UI reads/writes. Default: `forecastlens.db` inside the data folder below — never beside the code. |
| `FORECASTENGINE_DATA_DIR` | Overrides the whole user data folder (database, working copy, cache, exports). Default: `%LOCALAPPDATA%\ForecastEngine` on Windows, `~/.local/share/ForecastEngine` on Linux, `~/Library/Application Support/ForecastEngine` on macOS. |
| `FORECASTLENS_SECRET` | If set, every page requires this shared secret once per session |

All three are resolved in exactly one module, `core.paths`. Nothing else in
the codebase builds a path — `tests/unit/test_path_discipline.py` fails the
build if it does, because a path built by hand is how an app that works in
development dies as an exe.

## 2. Portable Windows executable

**Builds are automatic.** Every change on `main` produces a downloadable zip;
`docs/RELEASE.md` has the exact click-path on github.com, plus SmartScreen
and antivirus troubleshooting. There is no need to build locally.

A build is published only if the packaged app passes its own startup checks,
serves the interface, and produces **numbers identical to the source
version** (`tests/parity/`). A build that works but forecasts differently
fails the pipeline.

### Building locally (rarely needed)


Built with PyInstaller in **one-dir** mode (one-file is slower to start and
routinely quarantined by corporate antivirus). On a Windows build machine:

```bat
packaging\build_windows.bat
```

Produces `packaging\dist\ForecastEngine.zip`. The user unzips anywhere and
runs `ForecastEngine-Start.bat` — no Python, no installer, no admin rights,
no registry writes. Data lives in `%LOCALAPPDATA%\ForecastEngine`.

Verification happens in `.github/workflows/build-exe.yml` on a clean
`windows-latest` runner: startup self-check, headless launch with a probe of
`http://localhost:8501/_stcore/health`, the full parity suite, and the 300 MB
size budget.

Packaging notes baked into `packaging/forecast.spec`:

- Streamlit's `static/` and `runtime/` asset directories are bundled
  explicitly — PyInstaller does not find them.
- Launch goes through `streamlit.web.bootstrap`; there is no `streamlit`
  binary inside a bundle.
- `multiprocessing.freeze_support()` is the first statement of the entry
  point, or the exe fork-bombs on Windows.
- statsmodels, scipy.special and plotly submodules are declared as hidden
  imports with their data collected — PyInstaller cannot see imports these
  packages resolve at runtime.
- Frozen builds run joblib on the threading backend — worker processes would
  each re-launch the exe.
- Everything writable (database, logs, cache, exports) goes to
  `core.paths.data_dir()`. `sys._MEIPASS` is read-only at runtime; writing
  beside the bundled code is the classic frozen-build failure.
- The binary also runs headless: `--selfcheck`, `--version`, `--run-forecast`
  and `--export`. The parity suite uses those to prove the exe and the source
  produce identical results.

## 3. Hosted (optional)

Run the same Streamlit app behind your reverse proxy; terminate HTTPS at the
host. Set `FORECASTLENS_SECRET` for the shared-secret gate. Uploads are
session-scoped temp files; there are no outbound calls and no telemetry.

## Security posture

- Local-first; zero network dependency at runtime.
- Parameterized SQL only.
- Upload hardening: `.xlsx` allowlist, size cap, openpyxl read-only, macros
  never executed.
- The confidential dataset can never enter this repository: `.gitignore` +
  pre-commit hook + CI job reject every spreadsheet except
  `tests/fixtures/sample_public.xlsx`.
