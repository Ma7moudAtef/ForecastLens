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
    'main' label the sidebar used to show."""
    source = (APP / "main.py").read_text(encoding="utf-8")
    for title in ["Overview", "Data", "Configure & Run", "Explorer",
                  "Portfolio", "Accuracy", "Export"]:
        assert f'title="{title}"' in source, title
    assert "st.navigation" in source


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
    sort_options = at.selectbox[-1].options
    assert "description" in sort_options


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


def test_export_builds_downloads_with_identity_columns():
    """Export renders download buttons rather than tables; its payload is
    built through add_identity, verified directly here."""
    from app.components import db as app_db
    from app.components import items as item_utils

    at = AppTest.from_file(str(APP / "views" / "export.py"),
                           default_timeout=180).run()
    assert not at.exception
    assert len(at.download_button) >= 1, "no export download offered"

    stamp = app_db.stamp()
    run_id = app_db.repo().latest_complete_run_id()
    payload = item_utils.add_identity(
        app_db.load_forecasts(stamp, run_id),
        app_db.load_series(stamp), app_db.load_items(stamp))
    assert list(payload.columns[:4]) == ["item_code", "description", "line",
                                         "output_type"]
    assert "series_id" not in payload.columns
    assert payload["description"].str.len().gt(0).any()


def test_data_page_preloads_default_workbook():
    at = AppTest.from_file(str(APP / "views" / "data.py"),
                           default_timeout=300).run()
    assert not at.exception
    # summary metrics render, meaning a workbook was loaded with no user input
    assert any(m.value == "820" for m in at.metric), \
        "default workbook was not preloaded"
