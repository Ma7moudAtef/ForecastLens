"""M8: every page renders headlessly against a real result database without
raising. Streamlit's AppTest drives the scripts exactly as the server would."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.slow

APP = Path(__file__).resolve().parents[2] / "app"
PAGES = [
    APP / "main.py",
    APP / "pages" / "1_data.py",
    APP / "pages" / "2_configure_run.py",
    APP / "pages" / "3_explorer.py",
    APP / "pages" / "4_portfolio.py",
    APP / "pages" / "5_accuracy.py",
    APP / "pages" / "6_export.py",
]


@pytest.fixture(autouse=True)
def _point_ui_at_pipeline_db(pipeline_run, monkeypatch):
    monkeypatch.setenv("FORECASTLENS_DB", str(pipeline_run["db"]))


@pytest.mark.parametrize("page", PAGES, ids=[p.stem for p in PAGES])
def test_page_renders_without_exception(page):
    at = AppTest.from_file(str(page), default_timeout=120)
    at.run()
    assert not at.exception, at.exception


def test_home_shows_series_counts():
    at = AppTest.from_file(str(APP / "main.py"), default_timeout=120).run()
    values = [m.value for m in at.metric]
    assert "820" in values           # series count tile


def test_explorer_shows_run_and_picker():
    at = AppTest.from_file(str(APP / "pages" / "3_explorer.py"),
                           default_timeout=180).run()
    assert not at.exception
    assert len(at.selectbox) >= 1    # run picker present


def test_portfolio_shows_badge_tiles():
    at = AppTest.from_file(str(APP / "pages" / "4_portfolio.py"),
                           default_timeout=180).run()
    assert not at.exception
    assert len(at.metric) == 5       # five badge tiles
