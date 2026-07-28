"""Absolute/Relative mode resolution.

Mode is a property of the material's NATURE, not of data availability. If
consumption depends on a driver, the series is Relative and stays Relative —
permanently. Missing driver periods are ordinary data gaps: excluded from
fitting, flagged as warnings, but they never change mode. A Relative series
with too little driver history does NOT flip to Absolute; it falls through
the cold-start ladder. There is deliberately no coverage threshold.

Precedence: planner UI declaration > bom declared mode > inference.
Inference: any cons_rate present in the series → Relative; none → Absolute.
"""
from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    RELATIVE = "relative"
    ABSOLUTE = "absolute"


class ModeSource(str, Enum):
    INFERRED = "inferred"
    DERIVED = "derived"            # no cons_rate supplied; rate = qty ÷ driver
    DECLARED_BOM = "declared_bom"
    DECLARED_UI = "declared_ui"


_VALID = {m.value for m in Mode}


def resolve_mode(
    has_rate: bool,
    declared_bom: str | None = None,
    declared_ui: str | None = None,
    can_derive_rate: bool = False,
) -> tuple[Mode, ModeSource]:
    """Resolve a series' mode. Declared mode always wins over everything.

    `can_derive_rate` is True only when no rate was supplied, a driver exists
    for this series, and the planner asked for missing rates to be derived
    (rate.derive_missing). Without that explicit request, an absent rate means
    Absolute — data availability alone never changes a material's nature.
    """
    if declared_ui is not None and declared_ui.lower() in _VALID:
        return Mode(declared_ui.lower()), ModeSource.DECLARED_UI
    if declared_bom is not None and declared_bom.lower() in _VALID:
        return Mode(declared_bom.lower()), ModeSource.DECLARED_BOM
    if has_rate:
        return Mode.RELATIVE, ModeSource.INFERRED
    if can_derive_rate:
        return Mode.RELATIVE, ModeSource.DERIVED
    return Mode.ABSOLUTE, ModeSource.INFERRED
