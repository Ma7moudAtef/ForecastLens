# Deployment

## 1. From source (macOS / Linux / Windows)

```bash
pip install -e .
streamlit run app/main.py          # UI
python -m cli.run --input data.xlsx --db results.db   # headless batch
```

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
