"""The results workbook has to explain itself.

A planner acts on this file. An undocumented column, or a blank description
cell, is a defect in the deliverable — not a documentation nicety.
"""
from __future__ import annotations

import pandas as pd
import pytest

from core import export, identity
from core.export_guide import (
    COLUMN_GUIDE,
    DICTIONARY_SHEET,
    SHEET_PURPOSE,
    describe_column,
    guide_frame,
    tooltip,
)


def test_every_exportable_sheet_has_a_purpose():
    for sheet in export.SHEETS:
        assert SHEET_PURPOSE.get(sheet), f"{sheet} has no stated purpose"
    assert SHEET_PURPOSE.get(DICTIONARY_SHEET)


def test_every_documented_column_says_what_and_why():
    for sheet, columns in COLUMN_GUIDE.items():
        for column, entry in columns.items():
            what, why = entry
            assert what and why, f"{sheet}.{column} is only half explained"
            assert len(what) > 20, f"{sheet}.{column}: 'what' is too thin"
            assert len(why) > 20, f"{sheet}.{column}: 'why' is too thin"


def test_the_dictionary_avoids_jargon_a_planner_would_not_use():
    """The explanation cannot itself need explaining."""
    banned = ["eta-squared", "kruskal", "heteroske", "nnls",
              "series_id", "dataframe", "sqlite"]
    for sheet, columns in COLUMN_GUIDE.items():
        for column, (what, why) in columns.items():
            text = f"{what} {why}".lower()
            for word in banned:
                assert word not in text, \
                    f"{sheet}.{column} uses '{word}'"


def test_tooltip_joins_the_two_halves():
    text = tooltip("forecasts", "confidence")
    assert "→" in text
    assert tooltip("forecasts", "no_such_column") == ""


def test_guide_frame_covers_the_columns_actually_present():
    frames = {
        "forecasts": pd.DataFrame(columns=["item_code", "period",
                                           "target_value"]),
        "warnings": pd.DataFrame(columns=["code", "severity"]),
    }
    guide = guide_frame(frames)
    assert list(guide.columns) == ["sheet", "what this sheet is for", "column",
                                   "what it is", "why you need it"]
    assert len(guide) == 5
    assert set(guide["sheet"]) == {"forecasts", "warnings"}
    assert (guide["what it is"].str.len() > 0).all()
    # order follows the sheet, so it can be read side by side with it
    assert list(guide[guide["sheet"] == "forecasts"]["column"]) == [
        "item_code", "period", "target_value"]


def test_the_dictionary_never_documents_itself():
    frames = {DICTIONARY_SHEET: pd.DataFrame(columns=["sheet"]),
              "forecasts": pd.DataFrame(columns=["period"])}
    assert set(guide_frame(frames)["sheet"]) == {"forecasts"}


# --- descriptions -------------------------------------------------------------

def test_a_known_item_gets_its_real_description():
    assert identity.describe("A1", {"A1": "Ferro Silicon"}) == "Ferro Silicon"


@pytest.mark.parametrize("value", [None, "", "   ", float("nan"), pd.NA])
def test_a_blank_description_never_reaches_the_user(value):
    """Blank reads as 'the app lost it'. The marker reads as 'your bom sheet
    does not cover this item', which is the actual, fixable situation."""
    assert identity.describe("A1", {"A1": value}) == identity.MISSING_DESCRIPTION


def test_an_item_absent_from_the_lookup_says_so():
    assert identity.describe("A1", {}) == identity.MISSING_DESCRIPTION


@pytest.mark.parametrize("code", [None, "", float("nan"), pd.NA])
def test_a_row_about_no_item_is_labelled_differently(code):
    """A dataset-wide warning is not an item missing from bom, and must not
    be reported as one."""
    assert identity.describe(code, {"A1": "x"}) == identity.NO_ITEM


def test_add_identity_never_produces_a_blank_description():
    series = pd.DataFrame({"series_id": ["a|L1|X", "b|L1|X"],
                           "item_code": ["a", "b"],
                           "line": ["L1", "L1"], "output_type": ["X", "X"]})
    items = pd.DataFrame({"item_code": ["a"], "description": ["Known"]})
    out = identity.add_identity(
        pd.DataFrame({"series_id": ["a|L1|X", "b|L1|X"], "v": [1, 2]}),
        series, items)

    assert list(out["description"]) == ["Known", identity.MISSING_DESCRIPTION]
    assert not out["description"].eq("").any()


def test_expand_series_id_never_produces_a_blank_description():
    warnings = pd.DataFrame({
        "series_id": ["a|L1|X", None], "code": ["X", "Y"], "message": ["m", "n"]})
    out = identity.expand_series_id(warnings, {"a": "Known"})
    assert list(out["description"]) == ["Known", identity.NO_ITEM]
