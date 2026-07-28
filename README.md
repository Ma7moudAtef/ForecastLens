# ForecastLens

An adaptive, industry-agnostic **consumption forecasting engine** with a
Streamlit interface, packaged as a portable Windows executable.

ForecastLens ingests historical material consumption, determines how each
material behaves, competes multiple forecasting models under honest
rolling-origin validation, selects a winner, and explains its reasoning in
plain language a supply planner can act on. It works for steel, FMCG,
pharmaceuticals, trading companies and online retailers with data changes
only — no code changes.

It also asks whether a material's consumption depends on the *operating
conditions* of a period — how many units ran, which of them shared the plant,
whether a promotion was on — and forecasts on that where the data supports it.
Every item is tested; only the ones with a real, material effect get a
context-aware model, and the finding is reported either way.

Priorities, in order: **correctness → explainability → portability → speed →
UI polish.**

## Layout

```
core/        pure engine — pandas/numpy/statsmodels, zero streamlit imports (CI-enforced)
core/context/  operating-context features, always-on diagnostics, guards G1–G5
app/         Streamlit UI — reads completed results from SQLite, never computes
cli/         headless batch runner
tests/       unit / traps / integration / fixtures
packaging/   PyInstaller one-dir spec + Windows launcher
docs/        decisions and design notes
```

## Quick start (from source)

```bash
pip install -r requirements.txt   # runtime only — or: pip install -e .[dev]
streamlit run app/main.py         # UI (works from a plain clone, any cwd)
python -m cli.run --help          # headless batch run
pytest                            # verify (needs the [dev] extra)
```

Deploying to Streamlit Community Cloud: entrypoint `app/main.py`; the root
`requirements.txt` is what the platform installs — see `docs/deployment.md`.

## Data policy

The only spreadsheet allowed in this repository is
`tests/fixtures/sample_public.xlsx`. A pre-commit hook, `.gitignore` rules and
a CI job all reject any other spreadsheet — the real dataset is confidential
and must never enter version control. See `docs/decisions.md`.

## Development

- Install hooks once: `pre-commit install`
- Design decisions: `docs/decisions.md`
- Build milestones and specs: project documents (not in repo)
