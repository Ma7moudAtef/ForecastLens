"""Context features, derived automatically from the driver table.

One row per (period, unit, stream). Every feature here is knowable BEFORE the
period happens — each is read from the driver table, which carries the plan
for future periods as well as actuals for past ones. That is what makes them
legal forecasting regressors (guard G1): the engine never forecasts a
regressor in order to forecast the target.

A dataset with a single unit and a single stream produces constant features.
That is detected and the whole layer switches itself off — no errors, no
warnings, no wasted computation (guard G5).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.config import EngineConfig

#: identity of one atomic combination
KEY = ["unit", "stream"]
#: the derived feature columns, all knowable in advance
DERIVED_FEATURES = [
    "n_active", "is_solo", "own_share", "system_driver", "utilization",
    "mix_entropy",
]
#: user-supplied calendar factors are prefixed with this
CALENDAR_PREFIX = "ctx_"
#: label used when a period has no activity at all
IDLE_REGIME = "idle"
#: label for regimes too rare to fit on their own (guard G2)
OTHER_REGIME = "other"
#: separates the activity part of a regime label from supplied factors
LABEL_SEPARATOR = " | "
#: a supplied factor with more distinct values than this is a continuous
#: measurement, not an operating condition, and is left out of the label
MAX_LABEL_VALUES = 4


@dataclass
class ContextFrame:
    """Context features for every period, plus what they are worth.

    `has_variance` is False when the dataset simply has no operating
    variation to learn from — one unit, one stream, or a driver that is
    always the same shape. Downstream code then skips the context layer.
    """

    frame: pd.DataFrame
    has_variance: bool
    regime_counts: dict[str, int] = field(default_factory=dict)
    calendar_features: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def feature_names(self) -> list[str]:
        return [c for c in DERIVED_FEATURES if c in self.frame.columns] \
            + list(self.calendar_features)

    def for_key(self, unit, stream) -> pd.DataFrame:
        """Rows for one combination, indexed by period string."""
        if self.frame.empty:
            return pd.DataFrame()
        match = self.frame[(self.frame["unit"] == unit)
                           & (self.frame["stream"] == stream)]
        return match.set_index("period").sort_index()

    def period_summary(self) -> pd.DataFrame:
        """The features that describe the PERIOD rather than one combination
        — what ran, how much ran in total, how mixed it was. Used to fill in
        a combination's rows for periods where it did not run at all."""
        if self.frame.empty:
            return pd.DataFrame()
        columns = [c for c in ("regime_label", "n_active", "system_driver",
                               "mix_entropy", *self.calendar_features)
                   if c in self.frame.columns]
        return (self.frame.drop_duplicates("period", keep="first")
                .set_index("period")[columns].sort_index())

    def regime_at(self, period: str, unit, stream) -> str | None:
        rows = self.frame[(self.frame["period"] == period)
                          & (self.frame["unit"] == unit)
                          & (self.frame["stream"] == stream)]
        return None if rows.empty else str(rows.iloc[0]["regime_label"])


def regime_from_active_set(active: tuple[tuple, ...]) -> str:
    """A stable, readable key for a set of simultaneously active combos."""
    if not active:
        return IDLE_REGIME
    return "+".join(f"{u}:{s}" for u, s in active)


def _humanize_activity(label: str) -> str:
    if label == IDLE_REGIME:
        return "nothing running"
    named = []
    for part in str(label).split("+"):
        unit, _, stream = part.partition(":")
        named.append(f"{unit} ({stream})" if stream else unit)
    if len(named) == 1:
        return f"only {named[0]} running"
    return " and ".join([", ".join(named[:-1]), named[-1]]) + " running together"


def _humanize_factor(part: str) -> str:
    name, _, value = part.partition("=")
    name = name.replace("_", " ")
    if value == "1":
        return f"{name} on"
    if value == "0":
        return f"{name} off"
    return f"{name} {value}"


def humanize_regime(label: str) -> str:
    """The regime key as a planner would say it out loud."""
    if label == OTHER_REGIME:
        return "other, rarer conditions"
    parts = [p for p in str(label).split(LABEL_SEPARATOR) if p]
    if not parts:
        return "unknown conditions"
    activity = _humanize_activity(parts[0])
    if len(parts) == 1:
        return activity
    return activity + " with " + ", ".join(_humanize_factor(p)
                                           for p in parts[1:])


def _label_value(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _extend_labels(frame: pd.DataFrame,
                   calendar_features: list[str]) -> pd.DataFrame:
    """A promotion that is running is part of the period's operating
    condition, not something separate from it. Discrete supplied factors are
    folded into the regime label so the diagnostic layer and the
    regime-conditional model both see them without any extra machinery."""
    used = []
    for name in calendar_features:
        values = pd.to_numeric(frame[name], errors="coerce").dropna().unique()
        if 1 < len(values) <= MAX_LABEL_VALUES:
            used.append(name)
    if not used:
        return frame
    suffix = None
    for name in used:
        short = name[len(CALENDAR_PREFIX):] if name.startswith(CALENDAR_PREFIX) \
            else name
        piece = (short + "=" + pd.to_numeric(frame[name], errors="coerce")
                 .map(_label_value))
        suffix = piece if suffix is None else suffix + LABEL_SEPARATOR + piece
    frame["regime_label"] = frame["regime_label"] + LABEL_SEPARATOR + suffix
    return frame


def _entropy(shares: np.ndarray) -> float:
    """Shannon entropy of the driver split. 0 = one combo carries
    everything, higher = evenly mixed."""
    positive = shares[shares > 0]
    if len(positive) <= 1:
        return 0.0
    return float(-(positive * np.log(positive)).sum())


def derive(driver_agg: pd.DataFrame, cfg: EngineConfig,
           calendar: pd.DataFrame | None = None) -> ContextFrame:
    """Build the context frame from aggregated driver rows (actual + plan)."""
    if driver_agg is None or driver_agg.empty:
        return ContextFrame(pd.DataFrame(), False,
                            note="no driver table — context does not apply")

    d = driver_agg.rename(columns={"line": "unit", "output_type": "stream"}).copy()
    d = d[d["driver_type"].isin(["actual", "plan"])]
    if d.empty:
        return ContextFrame(pd.DataFrame(), False, note="no driver rows")
    d["period"] = d["period"].astype(str)
    d["driver_qty"] = pd.to_numeric(d["driver_qty"], errors="coerce")

    # one driver figure per (period, unit, stream); a plan row and an actual
    # row for the same period can only be an overlap, actual wins
    d["_rank"] = np.where(d["driver_type"] == "actual", 0, 1)
    d = (d.sort_values("_rank")
         .drop_duplicates(["period", "unit", "stream"], keep="first")
         .drop(columns="_rank"))

    combos = d[KEY].drop_duplicates()
    if len(combos) <= 1:
        return ContextFrame(
            pd.DataFrame(), False,
            note="a single unit and stream — no operating variation to learn")

    # activity floor: a combo counts as active when its driver reaches the
    # same reliability floor the rest of the engine uses
    medians = d.groupby(KEY)["driver_qty"].median().rename("median_driver")
    d = d.merge(medians, on=KEY, how="left")
    d["is_active"] = (d["driver_qty"].notna()
                      & (d["driver_qty"] > 0)
                      & (d["driver_qty"] >= cfg.driver.floor_fraction
                         * d["median_driver"]))

    # p95 of ACTUAL history only: utilization must not depend on the future
    actual = d[d["driver_type"] == "actual"]
    p95 = (actual.groupby(KEY)["driver_qty"].quantile(0.95)
           .rename("p95_driver")) if not actual.empty else pd.Series(dtype=float)
    d = d.merge(p95, on=KEY, how="left") if len(p95) else d.assign(p95_driver=np.nan)

    rows: list[dict] = []
    for period, group in d.groupby("period", sort=True):
        active = tuple(sorted(
            (r.unit, r.stream) for r in group.itertuples() if r.is_active))
        total = float(group.loc[group["is_active"], "driver_qty"].sum())
        shares = (group.loc[group["is_active"], "driver_qty"] / total
                  if total > 0 else pd.Series(dtype=float))
        entropy = _entropy(shares.to_numpy(dtype=float))
        label = regime_from_active_set(active)
        for r in group.itertuples():
            own = float(r.driver_qty) if pd.notna(r.driver_qty) else np.nan
            rows.append({
                "period": period,
                "unit": r.unit,
                "stream": r.stream,
                "driver_qty": own,
                "driver_type": r.driver_type,
                "active_set": active,
                "co_active_with": tuple(c for c in active
                                        if c != (r.unit, r.stream)),
                "n_active": len(active),
                "is_solo": bool(len(active) == 1 and (r.unit, r.stream) in active),
                "own_share": (own / total) if (total > 0 and own == own) else np.nan,
                "system_driver": total,
                "utilization": (own / r.p95_driver) if (
                    pd.notna(getattr(r, "p95_driver", np.nan))
                    and getattr(r, "p95_driver", 0) > 0 and own == own) else np.nan,
                "mix_entropy": entropy,
                "regime_label": label,
            })

    frame = pd.DataFrame(rows)
    calendar_features: list[str] = []
    if calendar is not None and not calendar.empty:
        frame, calendar_features = _attach_calendar(frame, calendar,
                                                    cfg.period_freq)
        frame = _extend_labels(frame, calendar_features)

    counts = (frame.loc[frame["driver_type"] == "actual", "regime_label"]
              .value_counts().to_dict())
    varying = _has_variance(frame, calendar_features)
    note = "" if varying else \
        "operating context never changes — the context layer is skipped"
    return ContextFrame(frame, varying, counts, calendar_features, note)


def _has_variance(frame: pd.DataFrame, calendar_features: list[str]) -> bool:
    """Something must actually change, or there is nothing to learn."""
    if frame.empty:
        return False
    historical = frame[frame["driver_type"] == "actual"]
    if historical.empty:
        return False
    if historical["regime_label"].nunique() > 1:
        return True
    for column in ["own_share", "utilization", "mix_entropy", *calendar_features]:
        if column not in historical.columns:
            continue
        values = pd.to_numeric(historical[column], errors="coerce").dropna()
        if len(values) > 1 and values.std(ddof=0) > 1e-9:
            return True
    return False


def _normalize_periods(values: pd.Series, freq: str) -> pd.Series:
    """A planner may write '2024-03', '2024-03-01' or a real date cell. All
    three mean the same period — resolve them to the run's own granularity so
    the merge actually matches."""
    text = values.astype(str).str.strip()
    parsed = pd.to_datetime(text, errors="coerce", format="mixed")
    out = text.copy()
    ok = parsed.notna()
    if ok.any():
        out[ok] = parsed[ok].dt.to_period(freq).astype(str)
    return out


def _attach_calendar(frame: pd.DataFrame, calendar: pd.DataFrame,
                     freq: str = "M") -> tuple[pd.DataFrame, list[str]]:
    """Fold a user-supplied context calendar in beside the derived features.

    Downstream code cannot tell a supplied factor from a derived one — that
    is the point: promotions, holidays, campaigns and shutdowns all become
    ordinary context features.
    """
    cal = calendar.copy()
    for column in ("unit", "stream"):
        if column not in cal.columns:
            cal[column] = pd.NA
    cal["period"] = _normalize_periods(cal["period"], freq)
    cal["factor_name"] = cal["factor_name"].astype(str)
    numeric = pd.to_numeric(cal["factor_value"], errors="coerce")
    # a non-numeric factor becomes an indicator per distinct value
    text_mask = numeric.isna() & cal["factor_value"].notna()
    cal["_value"] = numeric
    cal.loc[text_mask, "factor_name"] = (
        cal.loc[text_mask, "factor_name"] + "_"
        + cal.loc[text_mask, "factor_value"].astype(str))
    cal.loc[text_mask, "_value"] = 1.0
    cal = cal.dropna(subset=["_value"])
    if cal.empty:
        return frame, []

    names: list[str] = []
    out = frame
    for name, group in cal.groupby("factor_name"):
        column = f"{CALENDAR_PREFIX}{name}"
        names.append(column)
        keys = ["period"]
        has_unit = group["unit"].notna().any()
        has_stream = group["stream"].notna().any()
        if has_unit:
            keys.append("unit")
        if has_stream:
            keys.append("stream")
        slice_ = (group[keys + ["_value"]]
                  .drop_duplicates(keys, keep="last")
                  .rename(columns={"_value": column}))
        out = out.merge(slice_, on=keys, how="left")
        out[column] = out[column].fillna(0.0)
    return out, names


def pool_rare_regimes(labels: pd.Series, min_obs: int) -> pd.Series:
    """Guard G2: a regime seen fewer than `min_obs` times cannot be fitted on
    its own, so it joins an 'other' bucket rather than being dropped."""
    counts = labels.value_counts()
    rare = set(counts[counts < min_obs].index)
    if not rare:
        return labels
    return labels.where(~labels.isin(rare), OTHER_REGIME)
