"""The history gate: history length, pattern class and mode decide which
models may compete. A series with 4 months does not get to compete 13 models.

Routes (Part 4 of the model library):
  < 6 reliable periods        → cold-start ladder, no competition
  intermittent / lumpy        → Croston family, routed not competed
  6–23 periods, smooth/erratic→ non-seasonal set (+ anchor if Relative)
  ≥ 24 periods, smooth/erratic→ full set including seasonal
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.analyze.classify import PatternClass
from core.config import EngineConfig
from core.models.registry import (
    Candidate,
    build_intermittent_candidates,
    build_midrange_ets,
    build_nonseasonal_candidates,
    build_seasonal_candidates,
    filter_disabled,
)


class Route(str, Enum):
    COLD_START = "cold_start"
    ROUTED_INTERMITTENT = "routed_intermittent"
    COMPETE = "compete"


@dataclass
class GateDecision:
    route: Route
    candidates: list[Candidate]
    reason: str


def decide(n_reliable: int, pattern_class: str, mode: str,
           cfg: EngineConfig) -> GateDecision:
    min_hist = cfg.gate.min_history_competition
    seasonal_min = cfg.gate.seasonal_min_history

    if pattern_class in (PatternClass.INTERMITTENT.value, PatternClass.LUMPY.value):
        return GateDecision(
            route=Route.ROUTED_INTERMITTENT,
            candidates=filter_disabled(build_intermittent_candidates(cfg), cfg),
            reason=(f"Demand pattern is {pattern_class}: error metrics are "
                    "unreliable on zero-heavy series, so the series is routed "
                    "to the intermittent family instead of a competition."))

    if n_reliable < min_hist:
        return GateDecision(
            route=Route.COLD_START, candidates=[],
            reason=(f"Only {n_reliable} usable period(s) — below the "
                    f"{min_hist}-period competition threshold. Using the "
                    "cold-start ladder."))

    candidates = build_nonseasonal_candidates(cfg)
    if n_reliable >= seasonal_min:
        candidates = candidates + build_seasonal_candidates(cfg)
        reason = (f"{n_reliable} usable periods (≥ {seasonal_min}): full "
                  "candidate set including seasonal models.")
    else:
        if n_reliable >= 15:
            candidates = candidates + [build_midrange_ets(cfg)]
        reason = (f"{n_reliable} usable periods: non-seasonal candidate set "
                  f"(seasonal models need ≥ {seasonal_min}).")

    # drop candidates the history cannot honestly support
    fits = []
    for c in candidates:
        if c.build().min_history <= n_reliable:
            fits.append(c)
    return GateDecision(route=Route.COMPETE,
                        candidates=filter_disabled(fits, cfg), reason=reason)
