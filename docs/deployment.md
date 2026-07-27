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
| `FORECASTLENS_DB` | SQLite path the UI reads/writes (default `./forecastlens.db`) |
| `FORECASTLENS_SECRET` | If set, every page requires this shared secret once per session |

## 2. Portable Windows executable

Built with PyInstaller in **one-dir** mode (one-file is slower to start and
routinely quarantined by corporate antivirus). On a Windows build machine:

```bat
packaging\build_windows.bat
```

Produces `packaging\dist\ForecastLens.zip`. The user unzips anywhere and runs
`ForecastLens-Start.bat` — no Python, no installer, no admin rights, no
registry writes. Data lives in `%LOCALAPPDATA%\ForecastLens`.

Verification: the GitHub Actions workflow "Packaging smoke test (Windows)"
builds the hello-world spike on every packaging change and (on manual
dispatch) the full bundle, launches it headless on a clean `windows-latest`
runner, probes `http://localhost:8501/_stcore/health`, and enforces the
300 MB size budget.

Packaging notes baked into `packaging/forecast.spec`:

- Streamlit's `static/` and `runtime/` asset directories are bundled
  explicitly — PyInstaller does not find them.
- Launch goes through `streamlit.web.bootstrap`; there is no `streamlit`
  binary inside a bundle.
- `multiprocessing.freeze_support()` is the first statement of the entry
  point, or the exe fork-bombs on Windows.
- statsmodels submodules are declared as hidden imports with their data
  collected.
- Frozen builds run joblib on the threading backend — worker processes would
  each re-launch the exe.

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
