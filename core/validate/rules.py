"""Every validation rule, each returning ValidationWarning objects.

Nothing is ever auto-deleted: rules flag, store, and let the planner decide.
Severity semantics:
  FATAL   — the run cannot proceed (schema breakage)
  WARNING — data is suspicious or will be partially excluded; run proceeds
  INFO    — worth knowing; no effect on processing
"""
from __future__ import annotations

from enum import Enum

import numpy as np
import pandas as pd
from pydantic import BaseModel

from core.config import EngineConfig
from core.io.schema import RawTables

SERIES_KEY = ["item_code", "line", "output_type"]


class Severity(str, Enum):
    FATAL = "fatal"
    WARNING = "warning"
    INFO = "info"


class ValidationWarning(BaseModel):
    code: str
    severity: Severity
    message: str
    item_code: str | None = None
    line: str | None = None
    output_type: str | None = None
    count: int = 1

    def scope(self) -> str:
        if self.item_code is None:
            return "workbook"
        return f"({self.item_code}, {self.line or '-'}, {self.output_type or '-'})"


def _series_groups(consumption: pd.DataFrame):
    return consumption.groupby(SERIES_KEY, dropna=False)


def _key_kwargs(key: tuple) -> dict:
    item, line, output = key
    return {
        "item_code": None if pd.isna(item) else str(item),
        "line": None if pd.isna(line) else str(line),
        "output_type": None if pd.isna(output) else str(output),
    }


# --- rules --------------------------------------------------------------------

def rule_coercion_failures(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    out = []
    for col, n in raw.coercion_failures.items():
        sev = Severity.FATAL if col.endswith(".date") else Severity.WARNING
        out.append(ValidationWarning(
            code="COERCION_FAILURE", severity=sev, count=n,
            message=f"{n} value(s) in '{col}' could not be parsed and became null."))
    return out


def rule_duplicate_rows(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    out = []
    sizes = raw.consumption.groupby(SERIES_KEY + ["date"], dropna=False).size()
    dups = sizes[sizes > 1]
    if dups.empty:
        return out
    per_series = dups.groupby(level=SERIES_KEY).size()
    for key, n in per_series.items():
        out.append(ValidationWarning(
            code="DUPLICATE_PERIOD_ROWS", severity=Severity.INFO, count=int(n),
            message=(f"{n} period(s) have multiple consumption rows; they are "
                     "summed into one observation per period during preparation."),
            **_key_kwargs(key)))
    return out


def rule_negative_values(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    out = []
    cons = raw.consumption
    for col, label in [("qty_base", "quantity"), ("qty_ton", "tonnage"),
                       ("cost", "cost"), ("rate", "consumption rate")]:
        bad = cons[cons[col].notna() & (cons[col] < 0)]
        for key, grp in bad.groupby(SERIES_KEY, dropna=False):
            out.append(ValidationWarning(
                code="NEGATIVE_VALUE", severity=Severity.WARNING, count=len(grp),
                message=f"{len(grp)} row(s) have negative {label}; consumption "
                        "is never negative. Rows kept but flagged for review.",
                **_key_kwargs(key)))
    return out


def rule_missing_quantities(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    out = []
    bad = raw.consumption[raw.consumption["qty_base"].isna()]
    for key, grp in bad.groupby(SERIES_KEY, dropna=False):
        out.append(ValidationWarning(
            code="MISSING_QUANTITY", severity=Severity.WARNING, count=len(grp),
            message=f"{len(grp)} row(s) have no base-UOM quantity.",
            **_key_kwargs(key)))
    return out


def _driver_combos(raw: RawTables) -> set[tuple]:
    if raw.driver.empty:
        return set()
    return set(zip(raw.driver["line"], raw.driver["output_type"]))


def rule_orphan_series(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    """A series with a consumption rate whose (line, output_type) never appears
    in the driver table. This is not a gap — the denominator does not exist.
    The series is kept, stays Relative, and is excluded from reconstruction
    until the planner resolves it. We never guess a denominator."""
    out = []
    combos = _driver_combos(raw)
    if not combos:
        return out  # driver-less dataset: handled by rule_rates_without_driver_table
    rated = raw.consumption[raw.consumption["rate"].notna()]
    for key, _grp in rated.groupby(SERIES_KEY, dropna=False):
        _, line, output = key
        if (line, output) not in combos:
            out.append(ValidationWarning(
                code="ORPHAN_SERIES", severity=Severity.WARNING,
                message=(f"Series {(_key_kwargs(key)['item_code'], str(line), str(output))} "
                         f"has a consumption rate, but no driver record exists for "
                         f"output_type '{output}' on line '{line}' in ANY period — the "
                         "denominator does not exist. The series stays Relative and is "
                         "excluded from demand reconstruction until a driver is provided "
                         "or the planner declares it Absolute. No denominator is guessed; "
                         "the series is not deleted."),
                **_key_kwargs(key)))
    return out


def rule_derivable_rates(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    """Items with no cons_rate whose line and output DO have driver data.

    Surfaced so the option is discoverable, not applied automatically: an
    absent rate usually means the material's use does not track output, and
    dividing a steady quantity by a volatile driver manufactures noise.
    """
    if cfg.rate.derive_missing:
        return []
    combos = _driver_combos(raw)
    if not combos:
        return []
    unrated = raw.consumption[raw.consumption["rate"].isna()]
    if unrated.empty:
        return []
    items = {
        r.item_code for r in unrated.itertuples()
        if (r.line, r.output_type) in combos}
    if not items:
        return []
    return [ValidationWarning(
        code="RATE_DERIVABLE", severity=Severity.INFO, count=len(items),
        message=(f"{len(items)} item(s) have no consumption rate, but their "
                 "line and output do have production data. They are treated "
                 "as Absolute (quantity forecast directly). If their "
                 "consumption really does scale with output, switch on "
                 "'Derive missing consumption rates' on the Configure & Run "
                 "page and the engine will work the rate out as consumption "
                 "÷ production."))]


def rule_rates_without_driver_table(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    if not raw.driver.empty:
        return []
    n_rated = raw.consumption["rate"].notna().sum()
    if n_rated == 0:
        return []
    return [ValidationWarning(
        code="RATES_WITHOUT_DRIVER_TABLE", severity=Severity.WARNING, count=int(n_rated),
        message=(f"{n_rated} consumption row(s) carry a rate but the workbook has no "
                 "driver sheet at all. These series stay Relative by nature; without a "
                 "driver they fall through the cold-start ladder and cannot be "
                 "reconstructed into demand."))]


def rule_missing_driver_periods(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    """Relative series whose (line, output) exists in the driver table but some
    consumption periods have no ACTUAL driver record. Ordinary data gaps:
    excluded from fitting, never a mode change."""
    out = []
    combos = _driver_combos(raw)
    if not combos:
        return out
    act = raw.driver[raw.driver["driver_type"] == "actual"]
    act_keys = set(zip(act["date"], act["line"], act["output_type"]))
    rated = raw.consumption[raw.consumption["rate"].notna()]
    for key, grp in rated.groupby(SERIES_KEY, dropna=False):
        _, line, output = key
        if (line, output) not in combos:
            continue  # fully orphan — separate rule
        missing = {d for d in grp["date"].unique() if (d, line, output) not in act_keys}
        if missing:
            out.append(ValidationWarning(
                code="MISSING_DRIVER_PERIODS", severity=Severity.WARNING, count=len(missing),
                message=(f"{len(missing)} consumption period(s) have no actual driver "
                         "record. Treated as ordinary data gaps: excluded from fitting, "
                         "mode unchanged."),
                **_key_kwargs(key)))
    return out


def rule_nonpositive_driver(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    if raw.driver.empty:
        return []
    bad = raw.driver[raw.driver["driver_qty"].isna() | (raw.driver["driver_qty"] <= 0)]
    if bad.empty:
        return []
    return [ValidationWarning(
        code="NONPOSITIVE_DRIVER", severity=Severity.WARNING, count=len(bad),
        message=(f"{len(bad)} driver row(s) have zero, negative or missing quantity. "
                 "Rates against a near-zero denominator explode; affected periods are "
                 "marked unreliable during preparation."))]


def rule_items_missing_from_bom(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    known = set(raw.items["item_code"].dropna())
    used = set(raw.consumption["item_code"].dropna())
    missing = sorted(used - known)
    if not missing:
        return []
    preview = ", ".join(missing[:8]) + ("…" if len(missing) > 8 else "")
    share = len(missing) / max(len(used), 1)
    return [ValidationWarning(
        code="ITEM_NOT_IN_BOM", severity=Severity.WARNING, count=len(missing),
        message=(f"{len(missing)} of {len(used)} consumed item(s) ({share:.0%}) "
                 f"are absent from the bom sheet ({preview}). They have NO "
                 "description, so every table and export shows "
                 "'(not in bom)' where a name should be, and no category "
                 "information, so a cold-start series cannot borrow from "
                 "category siblings. Add them to the bom sheet, or switch on "
                 "'Only items listed in the bom' on Configure & Run to leave "
                 "them out of the forecast entirely."))]


def rule_mixed_mode_series(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    out = []
    for key, grp in _series_groups(raw.consumption):
        has = grp["rate"].notna()
        if has.any() and not has.all():
            out.append(ValidationWarning(
                code="MIXED_MODE_SERIES", severity=Severity.WARNING,
                count=int((~has).sum()),
                message=(f"{int((~has).sum())} of {len(grp)} rows lack a consumption "
                         "rate while others have one. The series is treated as Relative "
                         "(dependence on a driver is a property of the material); "
                         "rate-less periods are data gaps."),
                **_key_kwargs(key)))
    return out


def rule_insufficient_history(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    lens = _series_groups(raw.consumption)["date"].nunique()
    short = lens[lens < cfg.gate.min_history_competition]
    if short.empty:
        return []
    return [ValidationWarning(
        code="INSUFFICIENT_HISTORY", severity=Severity.INFO, count=len(short),
        message=(f"{len(short)} series have fewer than "
                 f"{cfg.gate.min_history_competition} observed periods. They skip the "
                 "model competition and use the cold-start ladder "
                 "(category prior → standard-rate anchor → naive)."))]


def rule_extreme_outliers(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    """Robust z-score (median/MAD) on non-zero quantities, per series."""
    out = []
    for key, grp in _series_groups(raw.consumption):
        vals = grp["qty_base"].dropna()
        vals = vals[vals > 0]
        if len(vals) < 8:
            continue
        med = vals.median()
        mad = (vals - med).abs().median()
        if mad == 0:
            continue
        z = 0.6745 * (vals - med).abs() / mad
        n_out = int((z > 5).sum())
        if n_out:
            out.append(ValidationWarning(
                code="EXTREME_OUTLIER", severity=Severity.INFO, count=n_out,
                message=(f"{n_out} observation(s) deviate more than 5 robust standard "
                         "deviations from the series median. Kept, not deleted — "
                         "review for data-entry errors."),
                **_key_kwargs(key)))
    return out


def rule_invalid_driver_type(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    if raw.driver.empty:
        return []
    bad = raw.driver[~raw.driver["driver_type"].isin(["actual", "plan"])]
    if bad.empty:
        return []
    vals = sorted(bad["driver_type"].astype(str).unique())
    return [ValidationWarning(
        code="INVALID_DRIVER_TYPE", severity=Severity.WARNING, count=len(bad),
        message=(f"{len(bad)} driver row(s) have production_type outside "
                 f"{{'actual','plan'}}: {vals}. These rows are ignored."))]


def rule_invalid_declared_mode(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    if "declared_mode" not in raw.items.columns:
        return []
    declared = raw.items["declared_mode"].dropna()
    bad = declared[~declared.str.lower().isin(["relative", "absolute"])]
    if bad.empty:
        return []
    return [ValidationWarning(
        code="INVALID_DECLARED_MODE", severity=Severity.WARNING, count=len(bad),
        message=(f"{len(bad)} bom row(s) declare a mode outside "
                 f"{{'relative','absolute'}}: {sorted(bad.unique())}. Ignored; "
                 "mode falls back to inference from cons_rate presence."))]


def rule_duplicate_bom_items(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    dup = raw.items["item_code"].value_counts()
    dup = dup[dup > 1]
    if dup.empty:
        return []
    return [ValidationWarning(
        code="DUPLICATE_BOM_ITEM", severity=Severity.WARNING, count=int(dup.sum()),
        message=f"item_code(s) appear more than once in bom: "
                f"{sorted(dup.index[:8])}. First occurrence wins.")]


ALL_RULES = [
    rule_coercion_failures,
    rule_derivable_rates,
    rule_duplicate_rows,
    rule_negative_values,
    rule_missing_quantities,
    rule_orphan_series,
    rule_rates_without_driver_table,
    rule_missing_driver_periods,
    rule_nonpositive_driver,
    rule_items_missing_from_bom,
    rule_mixed_mode_series,
    rule_insufficient_history,
    rule_extreme_outliers,
    rule_invalid_driver_type,
    rule_invalid_declared_mode,
    rule_duplicate_bom_items,
]


def run_all(raw: RawTables, cfg: EngineConfig) -> list[ValidationWarning]:
    warnings: list[ValidationWarning] = []
    for rule in ALL_RULES:
        warnings.extend(rule(raw, cfg))
    order = {Severity.FATAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    warnings.sort(key=lambda w: (order[w.severity], w.code, w.item_code or ""))
    return warnings


def has_fatal(warnings: list[ValidationWarning]) -> bool:
    return any(w.severity is Severity.FATAL for w in warnings)
