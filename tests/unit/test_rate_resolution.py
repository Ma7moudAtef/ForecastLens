"""The three rules for obtaining a consumption rate.

1. cons_rate supplied            → use it exactly, in the planner's units
2. no cons_rate but a driver     → derive qty ÷ driver, on request only
3. neither                       → Absolute, quantity forecast directly
"""
import numpy as np
import pandas as pd
import pytest

from core.config import EngineConfig
from core.io.schema import build_raw_tables
from core.prep.mode import Mode, ModeSource, resolve_mode
from core.prep.series_builder import build_series
from core.validate import rules

OFF = EngineConfig()
ON = EngineConfig(rate={"derive_missing": True})


def _bom(uom="k"):
    return pd.DataFrame([{
        "item_code": "A1", "item_description": "w", "uom": uom,
        "unit_price_$": 1.0, "unit_wt_kg": 0.1, "category_level1": "c",
        "category_level2": "c", "category_level3": "c"}])


def _cons(month, rate, qty=50.0, uom="k/t"):
    return {"date": f"2024-{month:02d}-01", "item_code": "A1",
            "cons_qty_base_uom": qty, "cons_qty_ton": qty / 1000,
            "cons_$": 1.0, "output_type": "x", "production_line": "a",
            "cons_rate": rate, "cons_rate_uom": uom if rate is not None else None}


def _prod(month, qty=100.0):
    return {"date": f"2024-{month:02d}-01", "production_uom1": "t",
            "production_qty1": qty, "production_uom2": "s",
            "production_qty2": 1.0, "output_type": "x",
            "production_line": "a", "production_type": "actual"}


def _raw(cons_rows, prod_rows=None, uom="k"):
    sheets = {"bom": _bom(uom), "consumption": pd.DataFrame(cons_rows)}
    if prod_rows is not None:
        sheets["prod"] = pd.DataFrame(prod_rows)
    return build_raw_tables(sheets)


# --- rule 1: supplied rate wins, in the planner's own units -------------------

def test_supplied_rate_is_used_exactly_as_given():
    """kg per tonne stays kg per tonne — the engine must never rescale it or
    recompute it from quantities."""
    raw = _raw([_cons(m, 0.5) for m in range(1, 7)],
               [_prod(m) for m in range(1, 7)])
    prep = build_series(raw, OFF)
    row = prep.series.iloc[0]
    assert row["mode"] == "relative"
    assert row["mode_source"] == "inferred"
    assert row["target_uom"] == "k/t"                  # the planner's units
    assert np.allclose(prep.observations["target"], 0.5)
    # qty ÷ driver would have been 50/100 = 0.5 here only by coincidence;
    # prove the supplied value is used even when it differs
    raw2 = _raw([_cons(m, 7.5, qty=50.0) for m in range(1, 7)],
                [_prod(m) for m in range(1, 7)])
    obs2 = build_series(raw2, OFF).observations
    assert np.allclose(obs2["target"], 7.5)            # not 0.5


def test_supplied_rate_is_untouched_even_when_derivation_is_on():
    raw = _raw([_cons(m, 7.5) for m in range(1, 7)],
               [_prod(m) for m in range(1, 7)])
    prep = build_series(raw, ON)
    assert prep.series.iloc[0]["mode_source"] == "inferred"
    assert np.allclose(prep.observations["target"], 7.5)


# --- rule 2: derive from consumption ÷ driver, on request ---------------------

def test_missing_rate_with_driver_stays_absolute_by_default():
    """Data availability alone never changes a material's nature."""
    raw = _raw([_cons(m, None) for m in range(1, 7)],
               [_prod(m) for m in range(1, 7)])
    row = build_series(raw, OFF).series.iloc[0]
    assert row["mode"] == "absolute"
    assert row["mode_source"] == "inferred"


def test_missing_rate_with_driver_is_derived_on_request():
    raw = _raw([_cons(m, None, qty=50.0) for m in range(1, 7)],
               [_prod(m, 100.0) for m in range(1, 7)])
    prep = build_series(raw, ON)
    row = prep.series.iloc[0]
    assert row["mode"] == "relative"
    assert row["mode_source"] == "derived"
    assert np.allclose(prep.observations["target"], 0.5)   # 50 ÷ 100
    assert row["target_uom"] == "k/t"                      # item uom / driver uom
    assert any(w.code == "RATE_DERIVED" for w in prep.warnings)


def test_derivation_leaves_periods_without_a_driver_undefined():
    """No denominator, no guess."""
    raw = _raw([_cons(m, None) for m in range(1, 7)],
               [_prod(m) for m in (1, 2, 3)])           # months 4-6 have none
    prep = build_series(raw, ON)
    target = prep.observations["target"].to_numpy(dtype=float)
    assert np.isfinite(target[:3]).all()
    assert np.isnan(target[3:]).all()


def test_derivation_needs_a_driver_for_that_line_and_output():
    """A driver elsewhere in the workbook does not make this series
    driver-dependent."""
    raw = _raw([_cons(m, None) for m in range(1, 7)],
               [{**_prod(m), "output_type": "OTHER"} for m in range(1, 7)])
    assert build_series(raw, ON).series.iloc[0]["mode"] == "absolute"


def test_declared_mode_still_beats_derivation():
    raw = _raw([_cons(m, None) for m in range(1, 7)],
               [_prod(m) for m in range(1, 7)])
    prep = build_series(raw, ON, mode_overrides={"A1": "absolute"})
    row = prep.series.iloc[0]
    assert row["mode"] == "absolute"
    assert row["mode_source"] == "declared_ui"


# --- rule 3: nothing to divide by → Absolute ---------------------------------

def test_no_rate_and_no_driver_is_absolute():
    raw = _raw([_cons(m, None) for m in range(1, 7)])       # no prod sheet
    for cfg in (OFF, ON):
        row = build_series(raw, cfg).series.iloc[0]
        assert row["mode"] == "absolute"
        assert row["mode_source"] == "inferred"


def test_absolute_target_stays_per_day_normalized():
    raw = _raw([_cons(m, None, qty=31.0) for m in range(1, 3)])
    obs = build_series(raw, OFF).observations
    days = pd.PeriodIndex(obs["period"], freq="M").days_in_month
    assert np.allclose(obs["target"] * days, obs["qty_base"])


# --- resolve_mode itself ------------------------------------------------------

def test_resolve_mode_precedence():
    assert resolve_mode(True) == (Mode.RELATIVE, ModeSource.INFERRED)
    assert resolve_mode(False) == (Mode.ABSOLUTE, ModeSource.INFERRED)
    assert resolve_mode(False, can_derive_rate=True) == \
        (Mode.RELATIVE, ModeSource.DERIVED)
    # a declaration outranks derivation
    assert resolve_mode(False, declared_bom="absolute", can_derive_rate=True) == \
        (Mode.ABSOLUTE, ModeSource.DECLARED_BOM)
    # a supplied rate outranks derivation
    assert resolve_mode(True, can_derive_rate=True) == \
        (Mode.RELATIVE, ModeSource.INFERRED)


# --- discoverability ----------------------------------------------------------

def test_derivable_items_are_flagged_so_the_option_is_discoverable():
    raw = _raw([_cons(m, None) for m in range(1, 7)],
               [_prod(m) for m in range(1, 7)])
    warnings = rules.run_all(raw, OFF)
    flagged = [w for w in warnings if w.code == "RATE_DERIVABLE"]
    assert len(flagged) == 1
    assert "Derive missing consumption rates" in flagged[0].message


def test_no_such_flag_once_derivation_is_enabled():
    raw = _raw([_cons(m, None) for m in range(1, 7)],
               [_prod(m) for m in range(1, 7)])
    assert not [w for w in rules.run_all(raw, ON) if w.code == "RATE_DERIVABLE"]
