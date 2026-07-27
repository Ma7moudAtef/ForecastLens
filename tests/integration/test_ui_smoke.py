"""M8: every view renders headlessly against a real result database without
raising. Streamlit's AppTest drives the scripts exactly as the server would."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.slow

APP = Path(__file__).resolve().parents[2] / "app"
VIEWS = sorted([p for p in (APP / "views").glob("*.py") if not p.name.startswith("__")])
PAGES = [APP / "main.py", *VIEWS]


@pytest.fixture(autouse=True)
def _point_ui_at_pipeline_db(pipeline_run, monkeypatch):
    monkeypatch.setenv("FORECASTLENS_DB", str(pipeline_run["db"]))


@pytest.mark.parametrize("page", PAGES, ids=[p.stem for p in PAGES])
def test_page_renders_without_exception(page):
    at = AppTest.from_file(str(page), default_timeout=180)
    at.run()
    assert not at.exception, at.exception


def test_navigation_declares_named_tabs():
    """The entrypoint routes to named views — 'Overview' replaces the bare
    'main' label the sidebar used to show. Accuracy is gone and Export is
    merged into Portfolio."""
    source = (APP / "main.py").read_text(encoding="utf-8")
    for title in ["Overview", "Data", "Configure & Run", "Explorer",
                  "Portfolio & Export"]:
        assert f'title="{title}"' in source, title
    assert "st.navigation" in source
    assert "Accuracy" not in source
    assert not (APP / "views" / "accuracy.py").exists()
    assert not (APP / "views" / "export.py").exists()


def test_overview_shows_series_counts_and_model_guide():
    at = AppTest.from_file(str(APP / "views" / "overview.py"),
                           default_timeout=180).run()
    assert not at.exception
    assert "820" in [m.value for m in at.metric]
    # the model explainer is present and covers each family
    text = " ".join(e.label for e in at.expander)
    for family in ["Baselines", "Averaging windows", "Exponential smoothing",
                   "Statistical", "Intermittent demand", "Domain anchors",
                   "Ensemble"]:
        assert family in text, family


def test_explorer_offers_items_by_description():
    at = AppTest.from_file(str(APP / "views" / "explorer.py"),
                           default_timeout=180).run()
    assert not at.exception
    item_widgets = [m for m in at.multiselect if "description" in m.label.lower()]
    assert item_widgets, "no description-first item picker on Explorer"
    options = item_widgets[0].options
    assert options and all("—" in o for o in options[:5]), options[:5]


def test_portfolio_shows_badge_tiles_and_identity_columns():
    at = AppTest.from_file(str(APP / "views" / "portfolio.py"),
                           default_timeout=180).run()
    assert not at.exception
    assert len(at.metric) == 5
    sort_by = next(s for s in at.selectbox if s.label == "Sort by")
    assert "description" in sort_by.options


@pytest.mark.parametrize("view", [p for p in VIEWS
                                  if p.stem in ("portfolio", "explorer")],
                         ids=lambda p: p.stem)
def test_rendered_tables_show_identity_columns_not_series_id(view):
    """Requirement: the user sees item code, description, line and output as
    separate columns — never the internal combined identifier."""
    at = AppTest.from_file(str(view), default_timeout=180).run()
    assert not at.exception
    rendered = [el.value for el in at.dataframe]
    assert rendered, f"{view.stem} rendered no tables"
    for frame in rendered:
        cols = set(getattr(frame, "columns", []))
        assert "series_id" not in cols, f"{view.stem} leaked series_id: {cols}"
    assert any({"item_code", "description", "line", "output_type"} <=
               set(getattr(f, "columns", [])) for f in rendered), \
        f"{view.stem} shows no identity columns"


def test_relative_item_charts_cons_rate_by_default():
    """Requirement: for a Relative item the forecast graph shows cons_rate —
    the quantity the engine actually models — not only reconstructed demand."""
    from app.components import db as app_db

    stamp = app_db.stamp()
    series = app_db.load_series(stamp)
    items = app_db.load_items(stamp)
    relative = series[(series["mode"] == "relative") &
                      (series["is_orphan"] == 0)].iloc[0]
    desc = items.set_index("item_code")["description"].get(
        relative["item_code"], "")

    at = AppTest.from_file(str(APP / "views" / "explorer.py"),
                           default_timeout=180).run()
    at.multiselect[0].set_value([f"{desc} — {relative['item_code']}"])
    at.multiselect[1].set_value([relative["line"]])
    at.multiselect[2].set_value([relative["output_type"]])
    at.run()
    assert not at.exception

    view_radio = [r for r in at.radio if "Chart shows" in r.label]
    assert view_radio, "no chart-view control for a Relative item"
    assert "cons_rate" in view_radio[0].value, view_radio[0].value
    assert view_radio[0].value == view_radio[0].options[0]  # rate is default


def test_portfolio_carries_the_merged_export_section():
    """Export lives on the Portfolio page now: the Excel workbook and the
    single-table CSV are both offered there."""
    from app.components import db as app_db
    from app.components import items as item_utils

    at = AppTest.from_file(str(APP / "views" / "portfolio.py"),
                           default_timeout=180).run()
    assert not at.exception
    labels = " ".join(b.label for b in at.download_button)
    assert "Excel workbook" in labels, labels
    assert "CSV" in labels, labels

    stamp = app_db.stamp()
    run_id = app_db.repo().latest_complete_run_id()
    payload = item_utils.add_identity(
        app_db.load_forecasts(stamp, run_id),
        app_db.load_series(stamp), app_db.load_items(stamp))
    assert list(payload.columns[:4]) == ["item_code", "description", "line",
                                         "output_type"]
    assert "series_id" not in payload.columns
    assert payload["description"].str.len().gt(0).any()


def test_run_picker_shows_friendly_numbers_not_identifiers():
    """Requirement: users see 'Run 1', 'Run 2'… never the internal id."""
    from app.components import db as app_db

    at = AppTest.from_file(str(APP / "views" / "portfolio.py"),
                           default_timeout=180).run()
    assert not at.exception
    run_options = at.selectbox[0].options
    assert run_options, "no run picker"
    run_ids = set(app_db.load_runs(app_db.stamp())["run_id"])
    for option in run_options:
        assert option.startswith("Run "), option
        assert not any(rid in option for rid in run_ids), option


def test_data_page_preloads_default_workbook():
    at = AppTest.from_file(str(APP / "views" / "data.py"),
                           default_timeout=300).run()
    assert not at.exception
    # summary metrics render, meaning a workbook was loaded with no user input
    assert any(m.value == "820" for m in at.metric), \
        "default workbook was not preloaded"


def test_configure_run_offers_scope_and_delete_controls():
    at = AppTest.from_file(str(APP / "views" / "configure_run.py"),
                           default_timeout=300).run()
    assert not at.exception

    scope = next(r for r in at.radio if r.label == "Run scope")
    assert scope.options == ["All materials", "A single item",
                             "A list of items"]

    buttons = " ".join(b.label for b in at.button)
    assert "Delete this run" in buttons
    assert "Delete all run history" in buttons


def test_deleting_a_run_removes_it_from_the_picker(tmp_path, monkeypatch):
    """End-to-end: press the delete button, the run disappears everywhere."""
    import shutil

    from app.components import db as app_db

    # work on a copy so the shared pipeline database stays intact
    source = app_db.db_path()
    copy = tmp_path / "copy.db"
    shutil.copy(source, copy)
    monkeypatch.setenv("FORECASTLENS_DB", str(copy))

    with app_db.repo() as repo:
        before = repo.list_runs()
        target = before.iloc[0]["run_id"]
        assert len(before) >= 1

    at = AppTest.from_file(str(APP / "views" / "configure_run.py"),
                           default_timeout=300).run()
    assert not at.exception
    delete = next(b for b in at.button if "Delete this run" in b.label)
    delete.click().run()
    assert not at.exception

    with app_db.repo() as repo:
        after = repo.list_runs()
        assert target not in set(after["run_id"])
        assert repo.get_selections(target).empty
        assert repo.get_forecasts(target).empty


def test_run_picker_survives_a_legacy_database(tmp_path, monkeypatch):
    """A database written before run_number/scope_note existed must render,
    not crash with 'float object has no attribute strip'."""
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE run (
            run_id TEXT PRIMARY KEY, name TEXT, created_at TEXT NOT NULL,
            input_hash TEXT, source_name TEXT, config_json TEXT NOT NULL,
            status TEXT NOT NULL, n_series INTEGER, duration_s REAL);
        INSERT INTO run VALUES ('legacy1', NULL, '2026-01-01T00:00:00',
                                '', '', '{}', 'complete', 820, 160.0);
    """)
    conn.commit()
    conn.close()
    monkeypatch.setenv("FORECASTLENS_DB", str(db))

    for view in ("portfolio.py", "explorer.py"):
        at = AppTest.from_file(str(APP / "views" / view),
                               default_timeout=180).run()
        assert not at.exception, f"{view}: {at.exception}"


def test_data_source_choice_is_sticky_across_reruns():
    """Requirement: once the user picks a source it stays picked — a rerun
    must not snap them back onto the default workbook."""
    at = AppTest.from_file(str(APP / "views" / "data.py"),
                           default_timeout=300).run()
    assert not at.exception
    source = at.radio[0]
    assert source.value.startswith("📦"), source.value

    other = next(o for o in source.options if o.startswith("📂"))
    source.set_value(other).run()
    assert at.radio[0].value == other, "choice lost on the same rerun"

    at.run()   # a further rerun, as any widget interaction would cause
    assert at.radio[0].value == other, "choice reverted to the default"
    assert at.session_state["data_source_choice"] == other
