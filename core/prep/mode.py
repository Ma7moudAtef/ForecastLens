"""Absolute/Relative mode resolution.

Mode is a property of the material's NATURE, not of data availability. If
consumption depends on a driver, the series is Relative and stays Relative —
permanently. Missing driver PERIODS are ordinary data gaps: excluded from
fitting, flagged as warnings, but they never change mode. A Relative series
with thin driver history does NOT flip to Absolute; it falls through the
cold-start ladder. There is deliberately no coverage threshold.

The one exception is the orphan: a series with a consumption rate whose
(line, output) has no driver record in ANY period. That is not a gap in the
history, it is the absence of the denominator itself — the rate can never be
turned into a quantity, no matter how many periods arrive. Such a series is
resolved Absolute and its quantity forecast directly, which is a usable
answer where a rate against nothing is not. It is not permanent: the moment
driver data appears the series resolves Relative again on the next run.

Precedence: planner UI declaration > bom declared mode > orphan > inference.
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
    NO_DRIVER = "no_driver"        # has a rate, but its denominator never exists
    DECLARED_BOM = "declared_bom"
    DECLARED_UI = "declared_ui"


_VALID = {m.value for m in Mode}


def resolve_mode(
    has_rate: bool,
    declared_bom: str | None = None,
    declared_ui: str | None = None,
    can_derive_rate: bool = False,
    driver_exists: bool = True,
) -> tuple[Mode, ModeSource]:
    """Resolve a series' mode. Declared mode always wins over everything.

    `can_derive_rate` is True only when no rate was supplied, a driver exists
    for this series, and the planner asked for missing rates to be derived
    (rate.derive_missing). Without that explicit request, an absent rate means
    Absolute — data availability alone never changes a material's nature.

    `driver_exists` is False only for an orphan: this (line, output) has no
    driver record in ANY period, so there is no denominator to be relative
    TO. That is a statement about the data's structure, not about how much
    history happens to be present, which is why it may change the mode where
    a run of missing periods may not.
    """
    if declared_ui is not None and declared_ui.lower() in _VALID:
        return Mode(declared_ui.lower()), ModeSource.DECLARED_UI
    if declared_bom is not None and declared_bom.lower() in _VALID:
        return Mode(declared_bom.lower()), ModeSource.DECLARED_BOM
    # only when the missing driver actually CHANGES the answer: a series with
    # no rate is Absolute for the ordinary reason, and labelling that
    # 'no_driver' would send a planner looking for production data they never
    # needed
    if has_rate and not driver_exists:
        return Mode.ABSOLUTE, ModeSource.NO_DRIVER
    if has_rate:
        return Mode.RELATIVE, ModeSource.INFERRED
    if can_derive_rate:
        return Mode.RELATIVE, ModeSource.DERIVED
    return Mode.ABSOLUTE, ModeSource.INFERRED
