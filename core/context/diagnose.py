"""Does the operating context actually move this series?

This runs for EVERY series, always — including series where no context model
could ever be fitted, and series where a moving average ends up winning. A
planner who is told "this material runs 38% heavier when both units are on"
has learned something useful even if the engine forecasts it with a flat
average.

The test is Kruskal-Wallis: non-parametric, assumes no normal distribution,
and behaves sensibly on the short, skewed samples this engine actually sees.
A p-value alone is never enough to act on — a large sample makes a 1%
difference "significant" — so the effect size and the plain percentage spread
between operating regimes are reported beside it, and BOTH have to clear
their bar before context models are allowed to compete (guard G4).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats as _stats

from core.config import EngineConfig
from core.context.features import humanize_regime, pool_rare_regimes

#: a group this small cannot contribute anything to a rank test
MIN_TEST_OBS = 2


@dataclass
class ContextDiagnosis:
    """What the operating context is worth for one series.

    `material` is the gate (G4): significant AND large enough to matter. It
    is the only field the model layer reads; everything else exists to be
    read by a human.
    """

    tested: bool = False
    n_regimes: int = 0
    n_observations: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    p_value: float | None = None
    statistic: float | None = None
    effect_size: float | None = None      # eta-squared from H
    spread_pct: float | None = None       # (max - min) / overall mean
    material: bool = False
    high_label: str = ""
    low_label: str = ""
    high_mean: float | None = None
    low_mean: float | None = None
    skip_reason: str = ""
    verdict: str = ""

    def to_row(self) -> dict:
        """Flat form for the result store."""
        import json

        return {
            "tested": int(self.tested),
            "n_regimes": int(self.n_regimes),
            "n_observations": int(self.n_observations),
            "p_value": self.p_value,
            "effect_size": self.effect_size,
            "spread_pct": self.spread_pct,
            "material": int(self.material),
            "verdict": self.verdict,
            "regime_counts_json": json.dumps(self.counts),
            "skip_reason": self.skip_reason,
        }


def _eta_squared(h: float, k: int, n: int) -> float | None:
    """Effect size for Kruskal-Wallis: the share of the ranked variation the
    regime split explains. Bounded to [0, 1] — the estimator can go slightly
    negative when the split explains nothing at all."""
    if n <= k:
        return None
    return float(min(1.0, max(0.0, (h - k + 1) / (n - k))))


def diagnose(y, regimes, cfg: EngineConfig,
             valid=None) -> ContextDiagnosis:
    """Test one series' target against its operating regimes.

    `y` and `regimes` are aligned period by period; `valid` marks the periods
    that may be used (unreliable and non-applicable periods are excluded the
    same way they are excluded from fitting).
    """
    y = np.asarray(y, dtype=float)
    labels = pd.Series(np.asarray(regimes, dtype=object)).astype(str)
    if len(labels) != len(y):
        return ContextDiagnosis(
            skip_reason="context is not aligned with this series",
            verdict="The operating context could not be matched to this "
                    "series, so it was not tested.")
    mask = np.ones(len(y), dtype=bool) if valid is None \
        else np.asarray(valid, dtype=bool)
    mask = mask & np.isfinite(y)

    y_use = y[mask]
    lab_use = labels[mask].reset_index(drop=True)
    if len(y_use) < 2 * MIN_TEST_OBS:
        return ContextDiagnosis(
            n_observations=len(y_use),
            skip_reason="too few usable periods to compare conditions",
            verdict="There is too little usable history to say whether "
                    "operating conditions change this material's use.")

    # rare regimes are pooled rather than dropped — an 'other' bucket keeps
    # their periods in the comparison instead of quietly deleting them (G2)
    pooled = pool_rare_regimes(lab_use, cfg.context.min_regime_obs)
    counts = pooled.value_counts().to_dict()
    kept = {name: int(n) for name, n in counts.items() if n >= MIN_TEST_OBS}

    if len(kept) < 2:
        only = next(iter(counts), "")
        return ContextDiagnosis(
            n_regimes=len(counts), n_observations=len(y_use),
            counts={k: int(v) for k, v in counts.items()},
            skip_reason="only one operating condition ever occurred",
            verdict=("Every usable period ran under the same conditions"
                     + (f" ({humanize_regime(only)})" if only else "")
                     + " — there is nothing to compare."))

    # everything from here on is measured over exactly the observations that
    # entered the comparison, so the effect size, the spread and the reported
    # count all describe the same thing
    keep_mask = pooled.isin(kept).to_numpy()
    y_use, pooled = y_use[keep_mask], pooled[keep_mask].reset_index(drop=True)
    groups = [y_use[(pooled == name).to_numpy()] for name in kept]

    if np.allclose(y_use, y_use[0]):
        return ContextDiagnosis(
            n_regimes=len(kept), n_observations=len(y_use), counts=kept,
            tested=False,
            skip_reason="the series is constant",
            verdict="This material's use never varies, so operating "
                    "conditions cannot be shown to change it.")

    try:
        stat, p = _stats.kruskal(*groups)
    except ValueError as exc:      # identical values in every group
        return ContextDiagnosis(
            n_regimes=len(kept), n_observations=len(y_use), counts=kept,
            skip_reason=f"the comparison could not be computed ({exc})",
            verdict="Operating conditions could not be compared for this "
                    "series.")

    means = {name: float(np.mean(group))
             for name, group in zip(kept, groups)}
    overall = float(np.mean(y_use))
    high = max(means, key=means.get)
    low = min(means, key=means.get)
    spread = (abs(means[high] - means[low]) / abs(overall)) \
        if overall != 0.0 and np.isfinite(overall) else None

    diag = ContextDiagnosis(
        tested=True,
        n_regimes=len(kept),
        n_observations=len(y_use),
        counts=kept,
        p_value=float(p),
        statistic=float(stat),
        effect_size=_eta_squared(float(stat), len(kept), len(y_use)),
        spread_pct=spread,
        high_label=high, low_label=low,
        high_mean=means[high], low_mean=means[low],
    )
    # G4: statistically real AND big enough to be worth modelling
    diag.material = bool(
        p < cfg.context.alpha
        and spread is not None
        and spread >= cfg.context.materiality)
    diag.verdict = verdict_text(diag, cfg)
    return diag


def verdict_text(diag: ContextDiagnosis, cfg: EngineConfig) -> str:
    """One or two sentences a planner can act on. No p-values, no jargon."""
    if not diag.tested:
        return diag.verdict
    conditions = f"{diag.n_regimes} operating condition" + \
        ("s" if diag.n_regimes != 1 else "")
    if diag.p_value is not None and diag.p_value >= cfg.context.alpha:
        return (f"Use looks the same whichever way the plant runs — compared "
                f"across {conditions}, the differences are no bigger than "
                "this material's normal period-to-period variation.")
    pct = (diag.spread_pct or 0.0) * 100
    detail = (f"Use is about {pct:.0f}% higher under "
              f"{humanize_regime(diag.high_label)} than under "
              f"{humanize_regime(diag.low_label)}")
    if not diag.material:
        return (f"{detail}. That is a consistent difference but a small one "
                f"(below the {cfg.context.materiality:.0%} threshold), so it "
                "is not worth forecasting separately.")
    return (f"{detail}, across {conditions} — a real and material effect, so "
            "context-aware models were allowed to compete for this series.")


def rejection_note(diag: ContextDiagnosis, cfg: EngineConfig) -> str:
    """Why the context models were not even offered this series."""
    if diag.material:
        return ""
    if not diag.tested:
        return (diag.verdict or "Operating context was not testable for this "
                "series.")
    if diag.p_value is not None and diag.p_value >= cfg.context.alpha:
        return ("Context-aware models were not offered: consumption does not "
                "differ measurably between operating conditions.")
    return ("Context-aware models were not offered: the difference between "
            f"operating conditions is real but under {cfg.context.materiality:.0%}, "
            "too small to justify a more complicated model.")
