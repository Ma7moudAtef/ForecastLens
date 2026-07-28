"""Three operating shapes the context layer has to get right.

    single_stream   one unit, one stream, nothing to compare — the layer must
                    switch itself off in silence and change no result.
    promotions      a plant-wide calendar factor that genuinely moves
                    consumption in the periods it covers.
    multi_regime    units that come and go, with consumption that really does
                    depend on which of them are running together.

Plus `pure_noise`, which looks exactly like multi_regime from the outside and
contains no context effect at all. That one exists to be failed.

Every shape is generated from a fixed seed and written to a temporary path,
never committed. `build(shape)` returns the sheet dict; `write(shape, path)`
turns it into a workbook the ordinary ExcelSource can load.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SEED = 20260401
UNITS = ["u1", "u2"]
STREAMS = ["s1"]
N_PERIODS = 42
START = "2022-01"


@dataclass
class Shape:
    """A generated workbook plus what the generator knows to be true about
    it — the tests assert against these, not against magic numbers."""

    sheets: dict[str, pd.DataFrame]
    truth: dict = field(default_factory=dict)


def _periods(n: int = N_PERIODS) -> pd.PeriodIndex:
    return pd.period_range(START, periods=n, freq="M")


def _bom(items: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "item_code": items,
        "item_description": [f"synthetic material {c}" for c in items],
        "uom": ["kg"] * len(items),
        "unit_price_$": [10.0] * len(items),
        "unit_wt_kg": [1.0] * len(items),
        "category_level1": ["synthetic"] * len(items),
        "category_level2": ["shape"] * len(items),
        "category_level3": ["group"] * len(items),
    })


def _prod_rows(periods, plan_periods, activity: dict) -> pd.DataFrame:
    """`activity` maps (unit, stream) -> array of driver quantities, one per
    period, zero meaning the unit did not run."""
    rows = []
    for (unit, stream), values in activity.items():
        for period, qty in zip(periods, values):
            if qty <= 0:
                continue
            rows.append({
                "date": period.to_timestamp(),
                "production_qty1": float(qty), "production_uom1": "ton",
                "production_qty2": np.nan, "production_uom2": None,
                "output_type": stream, "production_line": unit,
                "production_type": "actual",
            })
    # a plan for the horizon: the same conditions carried forward, so the
    # future is knowable (guard G1) without being identical to history
    for (unit, stream), values in activity.items():
        tail = values[-len(plan_periods):]
        for period, qty in zip(plan_periods, tail):
            if qty <= 0:
                continue
            rows.append({
                "date": period.to_timestamp(),
                "production_qty1": float(qty), "production_uom1": "ton",
                "production_qty2": np.nan, "production_uom2": None,
                "output_type": stream, "production_line": unit,
                "production_type": "plan",
            })
    return pd.DataFrame(rows)


def _cons_rows(periods, series: dict) -> pd.DataFrame:
    """`series` maps (item, unit, stream) -> (rate array, driver array)."""
    rows = []
    for (item, unit, stream), (rates, drivers) in series.items():
        for period, rate, driver in zip(periods, rates, drivers):
            if driver <= 0:
                continue
            rows.append({
                "date": period.to_timestamp(),
                "item_code": item,
                "cons_qty_base_uom": float(rate * driver),
                "cons_qty_ton": float(rate * driver) / 1000.0,
                "cons_$": float(rate * driver) * 10.0,
                "output_type": stream, "production_line": unit,
                "cons_rate": float(rate), "cons_rate_uom": "kg/ton",
            })
    return pd.DataFrame(rows)


def _empty_std() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "item_code", "std_cons_rate", "std_cons_rate_uom", "output_type",
        "production_line"])


# --- the shapes ---------------------------------------------------------------

def single_stream(horizon: int = 12) -> Shape:
    """One unit, one stream, always running. There is no operating variation
    to learn from and the layer must say so rather than inventing one."""
    rng = np.random.default_rng(SEED)
    periods = _periods()
    plan = pd.period_range(periods[-1] + 1, periods=horizon, freq="M")
    driver = np.full(len(periods), 100.0) + rng.normal(0, 4, len(periods))
    activity = {("u1", "s1"): driver}
    rate = 5.0 + rng.normal(0, 0.25, len(periods))
    return Shape(
        sheets={
            "bom": _bom(["SS001"]),
            "consumption": _cons_rows(periods, {("SS001", "u1", "s1"):
                                                (rate, driver)}),
            "prod": _prod_rows(periods, plan, activity),
            "consumption_figs": _empty_std(),
        },
        truth={"has_variance": False, "n_units": 1, "horizon": horizon})


def multi_regime(horizon: int = 12, effect: float = 0.40) -> Shape:
    """Two units that alternate between running alone and running together,
    with consumption that really is higher when they share the plant."""
    rng = np.random.default_rng(SEED + 1)
    periods = _periods()
    n = len(periods)
    # u1 always runs; u2 runs in a repeating on/off block, so both the solo
    # and the shared pattern have plenty of observations
    d1 = 100.0 + rng.normal(0, 5, n)
    pattern = np.array([(i // 3) % 2 == 0 for i in range(n)])
    d2 = np.where(pattern, 80.0 + rng.normal(0, 5, n), 0.0)
    base = 5.0
    rate1 = base * np.where(pattern, 1.0 + effect, 1.0) \
        + rng.normal(0, 0.15, n)
    rate2 = np.where(pattern, 7.0 + rng.normal(0, 0.2, n), 0.0)
    plan = pd.period_range(periods[-1] + 1, periods=horizon, freq="M")
    return Shape(
        sheets={
            "bom": _bom(["MR001", "MR002"]),
            "consumption": _cons_rows(periods, {
                ("MR001", "u1", "s1"): (rate1, d1),
                ("MR002", "u2", "s1"): (rate2, d2)}),
            "prod": _prod_rows(periods, plan,
                               {("u1", "s1"): d1, ("u2", "s1"): d2}),
            "consumption_figs": _empty_std(),
        },
        truth={"has_variance": True, "effect": effect, "horizon": horizon,
               "affected_series": "MR001|u1|s1"})


def promotions(horizon: int = 12, lift: float = 0.35) -> Shape:
    """A plant-wide factor the driver table cannot express — a promotion that
    the planner supplies through the context calendar and that really does
    lift consumption while it runs."""
    rng = np.random.default_rng(SEED + 2)
    periods = _periods()
    n = len(periods)
    d1 = 100.0 + rng.normal(0, 5, n)
    d2 = 90.0 + rng.normal(0, 5, n)
    on = np.array([(i % 4) in (0, 1) for i in range(n)])
    rate1 = 5.0 * np.where(on, 1.0 + lift, 1.0) + rng.normal(0, 0.12, n)
    rate2 = 6.0 + rng.normal(0, 0.2, n)
    plan = pd.period_range(periods[-1] + 1, periods=horizon, freq="M")

    all_periods = list(periods) + list(plan)
    flags = list(on) + [(len(periods) + i) % 4 in (0, 1)
                        for i in range(horizon)]
    calendar = pd.DataFrame({
        "period": [str(p) for p in all_periods],
        "factor_name": ["promotion"] * len(all_periods),
        "factor_value": [1.0 if f else 0.0 for f in flags],
    })
    return Shape(
        sheets={
            "bom": _bom(["PR001", "PR002"]),
            "consumption": _cons_rows(periods, {
                ("PR001", "u1", "s1"): (rate1, d1),
                ("PR002", "u2", "s1"): (rate2, d2)}),
            "prod": _prod_rows(periods, plan,
                               {("u1", "s1"): d1, ("u2", "s1"): d2}),
            "consumption_figs": _empty_std(),
            "context_calendar": calendar,
        },
        truth={"has_variance": True, "lift": lift, "horizon": horizon,
               "factor": "ctx_promotion", "affected_series": "PR001|u1|s1"})


def pure_noise(horizon: int = 12) -> Shape:
    """The trap. Identical operating variety to multi_regime, and consumption
    that ignores every bit of it. Any context model that claims to explain
    this series is overfitting."""
    rng = np.random.default_rng(SEED + 3)
    periods = _periods()
    n = len(periods)
    d1 = 100.0 + rng.normal(0, 5, n)
    pattern = np.array([(i // 3) % 2 == 0 for i in range(n)])
    d2 = np.where(pattern, 80.0 + rng.normal(0, 5, n), 0.0)
    rate1 = 5.0 + rng.normal(0, 0.5, n)          # independent of `pattern`
    rate2 = np.where(pattern, 7.0 + rng.normal(0, 0.5, n), 0.0)
    plan = pd.period_range(periods[-1] + 1, periods=horizon, freq="M")
    return Shape(
        sheets={
            "bom": _bom(["NZ001", "NZ002"]),
            "consumption": _cons_rows(periods, {
                ("NZ001", "u1", "s1"): (rate1, d1),
                ("NZ002", "u2", "s1"): (rate2, d2)}),
            "prod": _prod_rows(periods, plan,
                               {("u1", "s1"): d1, ("u2", "s1"): d2}),
            "consumption_figs": _empty_std(),
        },
        truth={"has_variance": True, "horizon": horizon,
               "noise_series": "NZ001|u1|s1"})


SHAPES = {
    "single_stream": single_stream,
    "multi_regime": multi_regime,
    "promotions": promotions,
    "pure_noise": pure_noise,
}


def write(shape: Shape, path) -> str:
    """Materialize a shape as a workbook the ordinary loader can read."""
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        for name, frame in shape.sheets.items():
            frame.to_excel(xl, sheet_name=name, index=False)
    return str(path)


def workbook(name: str, tmp_path, **kwargs) -> tuple[str, dict]:
    """Build one shape by name into `tmp_path`. Returns (path, truth)."""
    shape = SHAPES[name](**kwargs)
    return write(shape, tmp_path / f"{name}.xlsx"), shape.truth
