"""Downloadable sample workbook: the first N rows of every sheet plus a
data_dictionary sheet explaining each column and its function."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

DATA_DICTIONARY: list[tuple[str, str, str]] = [
    # (sheet, column, what it is / what the engine does with it)
    ("bom", "item_code", "Unique item identifier. Joins every other sheet."),
    ("bom", "item_description", "Human-readable name — the primary way items "
     "are picked throughout the app (the code stays visible)."),
    ("bom", "uom", "The item's base unit of measure."),
    ("bom", "unit_price_$", "Price per base unit; used for cost displays."),
    ("bom", "unit_wt_kg", "Weight per base unit in kilograms."),
    ("bom", "category_level1", "Broadest category. Cold-start series borrow "
     "pooled behaviour from category siblings (level 3 first, then 2, then 1)."),
    ("bom", "category_level2", "Middle category level."),
    ("bom", "category_level3", "Most specific category level."),
    ("bom", "mode", "OPTIONAL. Declare 'relative' or 'absolute' to fix the "
     "item's mode; a declaration always wins over what the data suggests."),
    ("consumption", "date", "Period date (any day inside the period)."),
    ("consumption", "item_code", "Which item was consumed."),
    ("consumption", "cons_qty_base_uom", "Quantity consumed in the item's own "
     "unit — the forecasting target for Absolute-mode items."),
    ("consumption", "cons_qty_ton", "Quantity converted to tonnes."),
    ("consumption", "cons_$", "Cost of the consumption."),
    ("consumption", "output_type", "Which product/output it was consumed for "
     "— one of the three dimensions of an atomic series."),
    ("consumption", "production_line", "Which line consumed it — a series "
     "dimension."),
    ("consumption", "cons_rate", "Consumption per unit of driver. Its "
     "presence marks the item RELATIVE (driver-dependent); the rate is then "
     "the forecasting target."),
    ("consumption", "cons_rate_uom", "Unit of the consumption rate."),
    ("prod", "date", "Driver period or day (daily plan rows are summed to "
     "the forecast period)."),
    ("prod", "production_uom1", "Unit of the main driver quantity."),
    ("prod", "production_qty1", "THE DRIVER: production output (tonnes, "
     "cases, orders…). Relative demand = rate × this. May be absent for "
     "trading businesses."),
    ("prod", "production_uom2", "Unit of the secondary quantity."),
    ("prod", "production_qty2", "Secondary output measure (informational)."),
    ("prod", "output_type", "Output the driver row belongs to."),
    ("prod", "production_line", "Line the driver row belongs to."),
    ("prod", "production_type", "'actual' (history, used for fitting) or "
     "'plan' (future, used to reconstruct demand from rates)."),
    ("consumption_figs", "item_code", "Item the standard applies to."),
    ("consumption_figs", "std_cons_rate", "Engineered standard consumption "
     "rate — competes as an anchor and benchmarks actual vs standard."),
    ("consumption_figs", "std_cons_rate_uom", "Unit of the standard rate."),
    ("consumption_figs", "output_type", "Output the standard applies to."),
    ("consumption_figs", "production_line", "Line the standard applies to."),
]


def build_sample_workbook(source: Path, n_rows: int = 10) -> bytes:
    """First `n_rows` of every sheet of `source` + the data_dictionary."""
    buffer = io.BytesIO()
    with pd.ExcelFile(source, engine="openpyxl") as xl:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            pd.DataFrame(DATA_DICTIONARY,
                         columns=["sheet", "column", "what it is / function"]
                         ).to_excel(writer, sheet_name="data_dictionary",
                                    index=False)
            for name in xl.sheet_names:
                xl.parse(name).head(n_rows).to_excel(
                    writer, sheet_name=name, index=False)
    return buffer.getvalue()
