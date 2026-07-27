"""Input contract and the external→internal mapping.

The word "production" is a steel-industry artifact that exists ONLY in the
input workbook. It is mapped to "driver" here, at the ingestion boundary, and
never appears again in core logic, the SQLite schema, or any internal API.
The engine never assumes a driver exists: the `prod` sheet may be absent or
empty (trading / e-commerce), in which case every series is Absolute.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


class SchemaError(Exception):
    """Fatal: the workbook cannot be processed at all."""


# --- sheet specs --------------------------------------------------------------
# external column -> internal column, per sheet. Order irrelevant.

BOM_SHEET = "bom"
CONSUMPTION_SHEET = "consumption"
DRIVER_SHEET = "prod"                     # external name only
STANDARD_RATE_SHEET = "consumption_figs"  # external name only

BOM_MAP = {
    "item_code": "item_code",
    "item_description": "description",
    "uom": "uom",
    "unit_price_$": "unit_price",
    "unit_wt_kg": "unit_wt",
    "category_level1": "cat_l1",
    "category_level2": "cat_l2",
    "category_level3": "cat_l3",
}
#: optional declared-mode column: a planner may declare a material dependent
#: (relative) or independent (absolute) regardless of what the data shows.
BOM_OPTIONAL_MAP = {"mode": "declared_mode"}

CONSUMPTION_MAP = {
    "date": "date",
    "item_code": "item_code",
    "cons_qty_base_uom": "qty_base",
    "cons_qty_ton": "qty_ton",
    "cons_$": "cost",
    "output_type": "output_type",
    "production_line": "line",
    "cons_rate": "rate",
    "cons_rate_uom": "rate_uom",
}

DRIVER_MAP = {
    "date": "date",
    "production_qty1": "driver_qty",
    "production_uom1": "driver_uom",
    "production_qty2": "driver_qty2",
    "production_uom2": "driver_uom2",
    "output_type": "output_type",
    "production_line": "line",
    "production_type": "driver_type",  # 'actual' | 'plan'
}

STANDARD_RATE_MAP = {
    "item_code": "item_code",
    "std_cons_rate": "std_rate",
    "std_cons_rate_uom": "std_uom",
    "output_type": "output_type",
    "production_line": "line",
}

REQUIRED_SHEETS = (BOM_SHEET, CONSUMPTION_SHEET)
OPTIONAL_SHEETS = (DRIVER_SHEET, STANDARD_RATE_SHEET)

_NUMERIC = {
    "qty_base", "qty_ton", "cost", "rate", "unit_price", "unit_wt",
    "driver_qty", "driver_qty2", "std_rate",
}
_DATED = {"date"}
#: dimension columns: keep as strings, strip whitespace, empty -> <NA>
_DIMENSION = {"item_code", "line", "output_type", "driver_type", "declared_mode"}


@dataclass
class RawTables:
    """Workbook contents after column mapping and dtype coercion.

    ``driver`` and ``standard_rates`` are empty DataFrames (correct columns,
    zero rows) when their sheets are absent — never None, so downstream code
    has no special cases.
    """

    items: pd.DataFrame
    consumption: pd.DataFrame
    driver: pd.DataFrame
    standard_rates: pd.DataFrame
    source_name: str = ""
    coercion_failures: dict[str, int] = field(default_factory=dict)


def _map_columns(df: pd.DataFrame, mapping: dict[str, str], sheet: str,
                 optional: dict[str, str] | None = None) -> pd.DataFrame:
    missing = [ext for ext in mapping if ext not in df.columns]
    if missing:
        raise SchemaError(f"sheet '{sheet}' is missing required columns: {missing}")
    full = dict(mapping)
    if optional:
        full.update({e: i for e, i in optional.items() if e in df.columns})
    out = df[list(full)].rename(columns=full)
    for internal in optional.values() if optional else ():
        if internal not in out.columns:
            out[internal] = pd.NA
    return out


def _coerce(df: pd.DataFrame, sheet: str, failures: dict[str, int]) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if col in _DATED:
            before = df[col].notna().sum()
            df[col] = pd.to_datetime(df[col], errors="coerce")
            failures[f"{sheet}.{col}"] = int(before - df[col].notna().sum())
        elif col in _NUMERIC:
            before = df[col].notna().sum()
            df[col] = pd.to_numeric(df[col], errors="coerce")
            failures[f"{sheet}.{col}"] = int(before - df[col].notna().sum())
        elif col in _DIMENSION:
            s = df[col].astype("string").str.strip()
            df[col] = s.mask(s == "")
    return df


def build_raw_tables(sheets: dict[str, pd.DataFrame], source_name: str = "") -> RawTables:
    """Map a dict of sheet-name -> DataFrame into internal RawTables."""
    for name in REQUIRED_SHEETS:
        if name not in sheets:
            raise SchemaError(f"required sheet '{name}' is missing from the workbook")

    failures: dict[str, int] = {}
    items = _coerce(
        _map_columns(sheets[BOM_SHEET], BOM_MAP, BOM_SHEET, BOM_OPTIONAL_MAP),
        BOM_SHEET, failures)
    consumption = _coerce(
        _map_columns(sheets[CONSUMPTION_SHEET], CONSUMPTION_MAP, CONSUMPTION_SHEET),
        CONSUMPTION_SHEET, failures)

    if DRIVER_SHEET in sheets and not sheets[DRIVER_SHEET].empty:
        driver = _coerce(_map_columns(sheets[DRIVER_SHEET], DRIVER_MAP, DRIVER_SHEET),
                         DRIVER_SHEET, failures)
    else:
        driver = pd.DataFrame(columns=list(DRIVER_MAP.values()))

    if STANDARD_RATE_SHEET in sheets and not sheets[STANDARD_RATE_SHEET].empty:
        standard_rates = _coerce(
            _map_columns(sheets[STANDARD_RATE_SHEET], STANDARD_RATE_MAP, STANDARD_RATE_SHEET),
            STANDARD_RATE_SHEET, failures)
    else:
        standard_rates = pd.DataFrame(columns=list(STANDARD_RATE_MAP.values()))

    return RawTables(items=items, consumption=consumption, driver=driver,
                     standard_rates=standard_rates, source_name=source_name,
                     coercion_failures={k: v for k, v in failures.items() if v})
