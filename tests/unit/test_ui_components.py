"""Unit tests for the presentation helpers: item identity, sample workbook,
and the requirement that every control carries an explanation."""
import ast
import io
from pathlib import Path

import pandas as pd
import pytest

from app.components import items as item_utils
from app.components import samples

ROOT = Path(__file__).resolve().parents[2]
VIEWS = sorted(p for p in (ROOT / "app" / "views").glob("*.py")
               if not p.name.startswith("__"))
#: components that render widgets directly must carry help text too
WIDGET_COMPONENTS = [ROOT / "app" / "components" / n
                     for n in ("db.py", "filebrowser.py")]
FIXTURE = ROOT / "tests" / "fixtures" / "sample_public.xlsx"


# --- item identity ------------------------------------------------------------

def test_label_puts_description_first():
    assert item_utils.label_of("code12", "Steel bolt") == "Steel bolt — code12"
    assert item_utils.label_of("code12", None) == "code12 (no description)"
    assert item_utils.label_of("code12", "") == "code12 (no description)"


def test_labels_sorted_by_description_with_undescribed_last():
    lookup = {"c1": "Zinc wire", "c2": "Alloy rod", "c3": None}
    labels = item_utils.build_labels(["c1", "c2", "c3"], lookup)
    assert list(labels) == ["Alloy rod — c2", "Zinc wire — c1",
                            "c3 (no description)"]
    assert labels["Alloy rod — c2"] == "c2"


def test_description_lookup_handles_both_column_names():
    internal = pd.DataFrame({"item_code": ["a"], "description": ["Widget"]})
    external = pd.DataFrame({"item_code": ["a"], "item_description": ["Widget"]})
    assert item_utils.description_lookup(internal) == {"a": "Widget"}
    assert item_utils.description_lookup(external) == {"a": "Widget"}
    assert item_utils.description_lookup(pd.DataFrame()) == {}


def test_expand_series_id_on_an_empty_frame():
    """Regression: splitting an empty column yields a frame with NO columns,
    so naive positional indexing raised KeyError — which broke the export
    whenever a run had zero warnings."""
    empty = pd.DataFrame(columns=["series_id", "code", "message"])
    out = item_utils.expand_series_id(empty, {"a": "Widget"})
    assert "series_id" not in out.columns
    assert {"item_code", "description", "line", "output_type"} <= set(out.columns)
    assert out.empty


def test_expand_series_id_populates_identity_columns():
    df = pd.DataFrame([{"series_id": "a|L1|X", "code": "W", "message": "m"},
                       {"series_id": None, "code": "W2", "message": "m2"}])
    out = item_utils.expand_series_id(df, {"a": "Widget"})
    first = out.iloc[0]
    assert (first["item_code"], first["description"], first["line"],
            first["output_type"]) == ("a", "Widget", "L1", "X")
    assert pd.isna(out.iloc[1]["item_code"])     # workbook-level warning
    assert "series_id" not in out.columns


def test_add_identity_replaces_series_id_with_four_columns():
    series = pd.DataFrame([{"series_id": "a|L1|X", "item_code": "a",
                            "line": "L1", "output_type": "X"}])
    items = pd.DataFrame([{"item_code": "a", "description": "Widget"}])
    df = pd.DataFrame([{"series_id": "a|L1|X", "period": "2026-07",
                        "target_value": 1.5}])
    out = item_utils.add_identity(df, series, items)
    assert list(out.columns[:4]) == ["item_code", "description", "line",
                                     "output_type"]
    assert "series_id" not in out.columns
    row = out.iloc[0]
    assert (row["item_code"], row["description"], row["line"],
            row["output_type"]) == ("a", "Widget", "L1", "X")


# --- sample workbook ----------------------------------------------------------

@pytest.fixture(scope="module")
def sample_bytes():
    return samples.build_sample_workbook(FIXTURE, n_rows=10)


def test_sample_has_ten_rows_per_sheet(sample_bytes):
    with pd.ExcelFile(io.BytesIO(sample_bytes), engine="openpyxl") as xl:
        for name in xl.sheet_names:
            if name == "data_dictionary":
                continue
            assert len(xl.parse(name)) <= 10, name


def test_sample_contains_data_dictionary_covering_every_column(sample_bytes):
    with pd.ExcelFile(io.BytesIO(sample_bytes), engine="openpyxl") as xl:
        assert "data_dictionary" in xl.sheet_names
        dictionary = xl.parse("data_dictionary")
        assert set(dictionary.columns) == {"sheet", "column",
                                           "what it is / function"}
        documented = set(zip(dictionary["sheet"], dictionary["column"]))
        for sheet in ["bom", "consumption", "prod", "consumption_figs"]:
            for column in xl.parse(sheet).columns:
                assert (sheet, column) in documented, (sheet, column)
        assert dictionary["what it is / function"].str.len().min() > 20


# --- help coverage ------------------------------------------------------------

WIDGETS_NEEDING_HELP = {
    "selectbox", "multiselect", "radio", "checkbox", "text_input",
    "number_input", "slider", "select_slider", "button", "download_button",
    "form_submit_button", "file_uploader", "metric", "data_editor",
    "toggle", "date_input",
}


def _calls(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            yield node


def test_every_interactive_widget_has_hover_help():
    """Requirement: every option, button and control explains itself on
    hover. st.data_editor takes no help= (it is documented by the caption
    and section header above it), so it is exempted here."""
    missing = []
    for view in VIEWS + WIDGET_COMPONENTS:
        tree = ast.parse(view.read_text(encoding="utf-8"))
        for call in _calls(tree):
            name = call.func.attr
            if name not in WIDGETS_NEEDING_HELP or name == "data_editor":
                continue
            if not any(k.arg == "help" for k in call.keywords):
                missing.append(f"{view.name}:{call.lineno} st.{name}")
    assert not missing, "widgets without hover help: " + ", ".join(missing)


def test_every_chart_is_rendered_with_an_explanation():
    """Charts have no help= parameter, so they must go through ui.chart(),
    which renders a hover ❓ beside them."""
    offenders = []
    for view in VIEWS:
        tree = ast.parse(view.read_text(encoding="utf-8"))
        for call in _calls(tree):
            if call.func.attr == "plotly_chart" and \
                    getattr(call.func.value, "id", None) == "st":
                offenders.append(f"{view.name}:{call.lineno}")
    assert not offenders, ("charts bypassing ui.chart() (no hover "
                           "explanation): " + ", ".join(offenders))


def test_headers_and_titles_never_print_the_series_id():
    """The combined identifier is internal plumbing. Whether rendered tables
    leak it is asserted at runtime in tests/integration/test_ui_smoke.py;
    here we catch it being formatted into visible headings."""
    offenders = []
    for view in VIEWS:
        tree = ast.parse(view.read_text(encoding="utf-8"))
        for call in _calls(tree):
            if call.func.attr not in {"header", "title", "subheader",
                                      "caption", "markdown"}:
                continue
            printed = ast.dump(ast.Module(body=[ast.Expr(a) for a in call.args],
                                          type_ignores=[]))
            if "'sid'" in printed or '"sid"' in printed or \
                    "series_id" in printed:
                offenders.append(f"{view.name}:{call.lineno}")
    assert not offenders, ("series identifier printed in a heading: "
                           + ", ".join(offenders))
