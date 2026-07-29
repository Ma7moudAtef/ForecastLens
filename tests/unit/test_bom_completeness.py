"""Items consumed but missing from the bom sheet.

They have real consumption history, so by default they are still forecast —
but they carry no description and no category, and that has to be visible
rather than showing up as a blank cell in a downloaded workbook.
"""
from __future__ import annotations

import pandas as pd

from core.config import EngineConfig, RunScope
from core.io.schema import RawTables
from core.validate import rules


def _raw(bom_codes, consumed_codes) -> RawTables:
    items = pd.DataFrame({
        "item_code": bom_codes,
        "description": [f"Material {c}" for c in bom_codes],
        "uom": ["kg"] * len(bom_codes),
        "unit_price": [1.0] * len(bom_codes),
        "unit_wt": [1.0] * len(bom_codes),
        "cat_l1": ["a"] * len(bom_codes),
        "cat_l2": ["b"] * len(bom_codes),
        "cat_l3": ["c"] * len(bom_codes),
        "declared_mode": [None] * len(bom_codes)})
    consumption = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01"] * len(consumed_codes)),
        "item_code": consumed_codes,
        "qty_base": [1.0] * len(consumed_codes),
        "qty_ton": [0.001] * len(consumed_codes),
        "cost": [1.0] * len(consumed_codes),
        "output_type": ["X"] * len(consumed_codes),
        "line": ["L1"] * len(consumed_codes),
        "rate": [None] * len(consumed_codes),
        "rate_uom": [None] * len(consumed_codes)})
    return RawTables(items=items, consumption=consumption,
                     driver=pd.DataFrame(), standard_rates=pd.DataFrame())


def test_missing_items_are_a_warning_not_a_footnote():
    """This reaches the planner as a blank-looking name in a workbook they
    plan against, so INFO is too quiet."""
    raw = _raw(["a", "b"], ["a", "b", "c", "d"])
    found = rules.rule_items_missing_from_bom(raw, EngineConfig())

    assert len(found) == 1
    warning = found[0]
    assert warning.severity is rules.Severity.WARNING
    assert warning.count == 2
    assert "c" in warning.message and "d" in warning.message


def test_the_warning_says_what_it_costs_and_how_to_resolve_it():
    raw = _raw(["a"], ["a", "b"])
    message = rules.rule_items_missing_from_bom(raw, EngineConfig())[0].message

    assert "(not in bom)" in message          # what the planner will see
    assert "category" in message              # what else is lost
    assert "bom sheet" in message             # the fix
    assert "50%" in message                   # the scale of the problem


def test_a_complete_bom_produces_no_warning():
    assert rules.rule_items_missing_from_bom(_raw(["a", "b"], ["a"]),
                                             EngineConfig()) == []


# --- the opt-in strict rule ---------------------------------------------------

def test_bom_items_only_is_off_by_default():
    """An item missing from bom still has real history. Dropping it is a
    governance decision the planner makes, not a default the engine imposes."""
    assert EngineConfig().scope.bom_items_only is False


def test_the_run_note_records_the_choice():
    assert RunScope().note() == "all items"
    assert RunScope(bom_items_only=True).note() == "bom-listed items only"

    scoped = RunScope(item_codes=["a", "b"], bom_items_only=True)
    assert scoped.note() == "2 items, bom-listed items only"
    assert RunScope(item_codes=["a"]).note() == "1 item (a)"
