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


def test_explorer_has_one_selection_control_with_nothing_preselected():
    """The picker is the only thing that decides what you see: no separate
    'split by' or 'group to chart' controls, and nothing pre-chosen."""
    at = AppTest.from_file(str(APP / "views" / "explorer.py"),
                           default_timeout=180).run()
    assert not at.exception

    labels = [m.label for m in at.multiselect]
    assert labels == ["Items (by description)", "Production lines",
                      "Output types"], labels
    assert all(m.value == [] for m in at.multiselect), \
        "a picker came pre-populated"

    selectboxes = [s.label for s in at.selectbox]
    assert "Group to chart" not in selectboxes, selectboxes
    source = (APP / "views" / "explorer.py").read_text(encoding="utf-8")
    assert "split_dims" not in source
    assert "Split results by" not in source


def test_explorer_default_view_combines_everything():
    """With nothing selected the whole catalogue is combined into one line,
    which is what 'leave it empty to combine across it' means."""
    at = AppTest.from_file(str(APP / "views" / "explorer.py"),
                           default_timeout=180).run()
    assert not at.exception
    captions = " ".join(c.value for c in at.caption)
    assert "shown combined" in captions
    tables = [el.value for el in at.dataframe]
    assert tables, "combined view rendered no table"
    combined = tables[-1]
    # one row per future period, not one per series (series end at different
    # times, so the periods span more than a single horizon)
    assert combined["period"].is_unique
    assert len(combined) < 200          # vs hundreds of underlying series
    assert combined["n_series"].max() > 50, "rows are not actually combined"


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
def test_rendered_tables_never_leak_the_series_id(view):
    at = AppTest.from_file(str(view), default_timeout=180).run()
    assert not at.exception
    rendered = [el.value for el in at.dataframe]
    assert rendered, f"{view.stem} rendered no tables"
    for frame in rendered:
        cols = set(getattr(frame, "columns", []))
        assert "series_id" not in cols, f"{view.stem} leaked series_id: {cols}"


def test_portfolio_shows_the_four_identity_columns():
    """Per-series output identifies an item by code, description, line and
    output type. (The Explorer's combined view has no per-series rows — its
    identity is shown as metrics on the single-series detail instead.)"""
    at = AppTest.from_file(str(APP / "views" / "portfolio.py"),
                           default_timeout=180).run()
    assert not at.exception
    rendered = [el.value for el in at.dataframe]
    assert any({"item_code", "description", "line", "output_type"} <=
               set(getattr(f, "columns", [])) for f in rendered)


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


def _pick_mode(at, mode: str):
    """Drive Explorer's combined view to one mode. AppTest.run() returns the
    refreshed tree, so the result must be used — elements from the previous
    tree are stale."""
    show = [r for r in at.radio if r.label == "Show"]
    if not show:
        return at
    option = next(o for o in show[0].options if o.lower().startswith(mode))
    return show[0].set_value(option).run()


def _rendered_text(at) -> str:
    """All markdown on the page, including the hover explanations rendered
    beside charts. (AppTest cannot read a plotly figure's own value, so the
    chart's explanation text is what identifies which chart was drawn.)"""
    return " ".join(m.value for m in at.markdown)


def test_combined_view_charts_rate_for_relative_and_quantity_for_absolute():
    """Requirement: the combined graph must not show demand for Relative
    items — it shows their consumption rate; Absolute items show quantity."""
    at = AppTest.from_file(str(APP / "views" / "explorer.py"),
                           default_timeout=300).run()
    assert not at.exception

    mode_radio = [r for r in at.radio if r.label == "Show"]
    assert mode_radio, "no mode chooser on a mixed selection"
    options = " ".join(mode_radio[0].options).lower()
    assert "relative" in options and "consumption rate" in options
    assert "absolute" in options and "consumption quantity" in options

    # Which chart was drawn is identified by a phrase unique to that branch
    # (AppTest cannot read a plotly figure's own contents) plus the results
    # table's column order, which is wording-independent.
    RATE_MARKER = "summed bounds do not divide into a meaningful rate"
    QUANTITY_MARKER = "consumption quantity for every series"

    # Relative: the driver-weighted consumption rate, table led by `rate`.
    rel = _pick_mode(at, "relative")
    assert not rel.exception
    rel_text = _rendered_text(rel)
    assert RATE_MARKER in rel_text
    assert QUANTITY_MARKER not in rel_text
    rel_cols = [list(d.value.columns) for d in rel.dataframe]
    assert rel_cols, "no results table"
    value_cols = [c for c in rel_cols[0] if c in ("rate", "demand")]
    assert value_cols[0] == "rate", rel_cols[0]

    # Absolute: summed consumption quantity, table led by `demand`.
    at2 = AppTest.from_file(str(APP / "views" / "explorer.py"),
                            default_timeout=300).run()
    absolute = _pick_mode(at2, "absolute")
    assert not absolute.exception
    abs_text = _rendered_text(absolute)
    assert QUANTITY_MARKER in abs_text
    assert RATE_MARKER not in abs_text
    abs_cols = [list(d.value.columns) for d in absolute.dataframe]
    value_cols = [c for c in abs_cols[0] if c in ("rate", "demand")]
    assert value_cols[0] == "demand", abs_cols[0]


def test_combined_relative_rate_is_driver_weighted_not_averaged():
    """The combined rate is Σ(rate·driver) ÷ Σdriver over the member
    series-periods — a driver-weighted average of the recorded rates, not a
    plain average, and not derived from quantities."""
    import numpy as np

    from app.components import db as app_db
    from core.forecast.aggregate import aggregate_forecasts

    stamp = app_db.stamp()
    run_id = app_db.repo().latest_complete_run_id()
    series = app_db.load_series(stamp)
    forecasts = app_db.load_forecasts(stamp, run_id)

    relative = series[series["mode"] == "relative"]
    agg = aggregate_forecasts(forecasts, relative, group_dims=[])
    assert not agg.empty

    row = agg[agg["rate"].notna() & (agg["driver_plan"] > 0)].iloc[0]
    members = forecasts[
        forecasts["series_id"].isin(set(relative["series_id"])) &
        (forecasts["period"] == row["period"])].dropna(subset=["driver_plan"])

    weighted = ((members["target_value"] * members["driver_plan"]).sum()
                / members["driver_plan"].sum())
    assert row["rate"] == pytest.approx(weighted)
    assert not np.isclose(row["rate"], members["target_value"].mean()), \
        "combined rate equals a plain average — rates must be driver-weighted"

    # the displayed production counts each line once, not once per item
    assert row["driver_plan"] < members["driver_plan"].sum()
    assert row["driver_plan"] == pytest.approx(
        members.merge(relative[["series_id", "line", "output_type"]],
                      on="series_id")
        .drop_duplicates(["line", "output_type"])["driver_plan"].sum())


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


def test_overview_workflow_matches_the_real_tabs():
    """Requirement: the workflow text must describe the tabs that actually
    exist — no Accuracy, and Export merged into Portfolio."""
    import re

    nav_source = (APP / "main.py").read_text(encoding="utf-8")
    nav_titles = re.findall(r'st\.Page\([^)]*?title="([^"]+)"', nav_source)
    assert len(nav_titles) >= 4, nav_titles

    at = AppTest.from_file(str(APP / "views" / "overview.py"),
                           default_timeout=180).run()
    assert not at.exception
    workflow = next(m.value for m in at.markdown if "**Workflow**" in m.value)

    # every tab except Overview itself is described, in navigation order
    described = [t for t in nav_titles if t != "Overview"]
    positions = [workflow.find(t) for t in described]
    assert all(p >= 0 for p in positions), \
        f"tabs missing from the workflow: " \
        f"{[t for t, p in zip(described, positions) if p < 0]}"
    assert positions == sorted(positions), "workflow order differs from tabs"

    # and nothing that no longer exists is mentioned
    assert "Accuracy" not in workflow
    assert not re.search(r"\*\*.{0,4}Export\*\*", workflow), \
        "Export is described as its own tab"


def test_arima_is_not_a_planner_facing_option():
    at = AppTest.from_file(str(APP / "views" / "configure_run.py"),
                           default_timeout=300).run()
    assert not at.exception
    for widget in list(at.checkbox) + list(at.multiselect) + list(at.radio):
        assert "ARIMA" not in widget.label, widget.label
        options = getattr(widget, "options", []) or []
        assert not any("ARIMA" in str(o) for o in options), options
    source = (APP / "views" / "configure_run.py").read_text(encoding="utf-8")
    assert "enable_arima" not in source


def test_run_tab_offers_a_log_view():
    """The log expander only exists once a run has produced lines, so drive
    the state directly rather than launching a real batch."""
    from app.components import run_state

    at = AppTest.from_file(str(APP / "views" / "configure_run.py"),
                           default_timeout=300)
    at.run()
    assert not at.exception
    assert hasattr(run_state, "request_cancel")

    # a finished run leaves its log available to read and download
    run_state._state.update({"running": False, "run_id": "abc",
                             "log": ["12:00:00  Reading workbook: x.xlsx",
                                     "12:00:05  Run finished in 5s"],
                             "started_at": 0.0, "finished_at": 5.0})
    try:
        at.run()
        assert not at.exception
        assert any("Run log" in e.label for e in at.expander)
        assert any("Download log" in b.label for b in at.download_button)
    finally:
        run_state._state.update({"run_id": None, "log": [], "started_at": None,
                                 "finished_at": None})


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


def test_intelligence_card_reports_operating_context_for_every_item():
    """The amendment's requirement: the context finding is shown whether or
    not a context-aware model was used — including "it makes no difference
    here", which is an answer in its own right."""
    from app.components import db as app_db

    stamp = app_db.stamp()
    series = app_db.load_series(stamp)
    items = app_db.load_items(stamp)
    context = app_db.load_series_context(stamp).set_index("series_id")
    assert not context.empty, "the pipeline wrote no context diagnoses"

    # deliberately pick an item the context layer found NOTHING for
    quiet = context[context["material"] == 0].index
    row = series[series["series_id"].isin(quiet)
                 & (series["n_reliable"] >= 6)].iloc[0]
    desc = items.set_index("item_code")["description"].get(
        row["item_code"], "")

    at = AppTest.from_file(str(APP / "views" / "explorer.py"),
                           default_timeout=180).run()
    at.multiselect[0].set_value([f"{desc} — {row['item_code']}"])
    at.multiselect[1].set_value([row["line"]])
    at.multiselect[2].set_value([row["output_type"]])
    at.run()
    assert not at.exception

    rendered = _rendered_text(at)
    assert "Operating context" in rendered
    verdict = context.loc[row["series_id"], "verdict"]
    banners = " ".join(el.value for el in at.info) + " " + \
        " ".join(el.value for el in at.success)
    assert verdict[:60] in banners, "the card did not show the finding"


def test_overview_explains_the_context_models():
    at = AppTest.from_file(str(APP / "views" / "overview.py"),
                           default_timeout=180).run()
    assert not at.exception
    labels = " ".join(e.label for e in at.expander)
    assert "Operating context" in labels
    body = " ".join(e.value for e in at.markdown)
    for phrase in ("Fixed+Variable", "Regime-Conditional",
                   "Context Regression"):
        assert phrase in body


def test_configure_run_offers_the_context_controls():
    at = AppTest.from_file(str(APP / "views" / "configure_run.py"),
                           default_timeout=180).run()
    assert not at.exception
    boxes = {c.label for c in at.checkbox}
    assert "Use operating context" in boxes
    sliders = {s.label for s in at.slider}
    assert "Minimum context effect to act on" in sliders
