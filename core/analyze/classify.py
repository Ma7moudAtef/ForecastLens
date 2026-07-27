"""Syntetos-Boylan demand pattern classification (ADI / CV²).

Computed over the series' active span — gap periods count as zero demand.
Classification is insight only, with exactly one exception: Intermittent and
Lumpy series are ROUTED to the Croston family, not competed — error metrics
are unreliable on zero-heavy series and a competition there selects noise.
"""
from __future__ import annotations

from enum import Enum

import numpy as np

ADI_THRESHOLD = 1.32
CV2_THRESHOLD = 0.49


class PatternClass(str, Enum):
    SMOOTH = "smooth"
    ERRATIC = "erratic"
    INTERMITTENT = "intermittent"
    LUMPY = "lumpy"
    TOO_SHORT = "too_short"


#: classes routed straight to the intermittent family
ROUTED_CLASSES = {PatternClass.INTERMITTENT, PatternClass.LUMPY}


def adi_cv2(values: np.ndarray) -> tuple[float | None, float | None]:
    """ADI = periods ÷ periods with non-zero demand;
    CV² = squared coefficient of variation of the non-zero values."""
    values = np.asarray(values, dtype=float)
    nonzero = values[values > 0]
    if len(nonzero) == 0:
        return None, None
    adi = len(values) / len(nonzero)
    mean = nonzero.mean()
    cv2 = float((nonzero.std(ddof=0) / mean) ** 2) if mean > 0 else None
    return float(adi), cv2


def classify(values: np.ndarray, min_len: int = 6) -> tuple[PatternClass, float | None, float | None]:
    """Classify a span of target values (gaps already included as zeros)."""
    values = np.asarray(values, dtype=float)
    if len(values) < min_len:
        return PatternClass.TOO_SHORT, *adi_cv2(values)
    adi, cv2 = adi_cv2(values)
    if adi is None or cv2 is None:
        return PatternClass.TOO_SHORT, adi, cv2
    if adi < ADI_THRESHOLD:
        cls = PatternClass.SMOOTH if cv2 < CV2_THRESHOLD else PatternClass.ERRATIC
    else:
        cls = PatternClass.INTERMITTENT if cv2 < CV2_THRESHOLD else PatternClass.LUMPY
    return cls, adi, cv2
