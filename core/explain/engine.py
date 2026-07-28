"""Plain-language explanations for every automatic decision.

No jargon, no metric dumps: a planner must be able to read every sentence.
The word MASE never appears in explanation text — it is "validation error".

Special cases with dedicated text: the orphan series with no driver; cold
start via category prior or standard-rate anchor; the standard-rate anchor
winning an open competition; TSB signalling obsolescence; low-driver periods
excluded as unreliable; a planner-declared mode; the smoothing-bias caveat on
volatile drivers.
"""
from __future__ import annotations

import numpy as np

TREND_FAMILY = {"Drift", "Holt", "DampedHolt"}
SEASONAL_FAMILY = {"SeasonalNaive", "HoltWinters"}
LEVEL_FAMILY = {"Mean", "MovingAverage", "WeightedMovingAverage", "SES"}
SMOOTHING_FAMILY = {"SES", "Holt", "DampedHolt", "HoltWinters", "ETS", "Theta"}
CONTEXT_FAMILY = {"FixedPlusVariable", "RegimeConditional", "ContextRegression"}


def _windows(n: int) -> str:
    return f"{n} test window" + ("s" if n != 1 else "")


def selection_reason(selection: dict, meta: dict) -> str:
    """The why-this-model text. `selection` is the pipeline's selection dict
    (route, reason_code, winner name/explain, mase, n_origins…); `meta` the
    series behaviour row (n_reliable, pattern_class, mode, is_orphan…)."""
    code = selection["reason_code"]
    name = selection["model_name"]
    n_reliable = int(meta.get("n_reliable") or 0)
    explain = selection.get("winner_explain") or ""

    if code == "planner_override":
        return (f"Selected by planner override: {name} is locked for this "
                f"series until unlocked. {explain}")

    if code == "competition_winner":
        n_origins = int(selection.get("n_origins") or 0)
        lead = (f"{name} gave the lowest validation error across "
                f"{_windows(n_origins)}, using {n_reliable} periods of usable "
                "history.")
        return f"{lead} {explain}".strip()

    if code == "cold_start_standard_rate":
        return (f"Only {n_reliable} period(s) of usable history — too little "
                "to validate a fitted model honestly. The engineered standard "
                "consumption rate is the most credible estimate for this "
                "driver-dependent material.")

    if code == "cold_start_category_prior":
        return (f"Only {n_reliable} period(s) of usable history. {explain} "
                "The forecast will switch to the item's own behaviour once "
                "enough history accumulates.")

    if code == "cold_start_naive":
        return (f"Only {n_reliable} period(s) of usable history and no "
                "standard rate or comparable category items to borrow from; "
                "carrying the most recent actual forward is the only honest "
                "estimate.")

    if code == "cold_start_zero":
        return ("No usable consumption signal exists for this series yet; "
                "forecasting zero until real movement is recorded.")

    if code == "routed_sba":
        return ("Demand is sporadic (many zero periods), where ordinary "
                "error comparison selects noise — so the series is routed, "
                f"not competed. {explain}")

    if code == "routed_tsb_obsolescence":
        return ("Demand is sporadic and the series has gone quiet for an "
                f"extended stretch. {explain} The forecast decays toward zero "
                "the longer the silence lasts.")

    if code == "routed_zero":
        return ("No demand has ever been recorded in this series' history; "
                "the honest forecast is zero.")

    return explain or f"{name} selected."


def rejection_reason(candidate: dict, winner: dict, meta: dict) -> str:
    """One sentence for why a losing candidate lost."""
    status = candidate.get("status")
    name = candidate.get("model_name")
    if status == "failed":
        # a context model refuses to fit in plain words ("the driver barely
        # varies…"); pass that straight through rather than burying it
        detail = str(candidate.get("fail_reason") or "")
        _, _, message = detail.partition(": ")
        if name in CONTEXT_FAMILY and message:
            return f"{name} could not be used here — {message}."
        return (f"{name} failed to fit this series and was disqualified "
                "(the run continued without it).")
    if status == "skipped":
        return (f"{name} could not be validated honestly — too little "
                "history for enough test windows.")

    c_mase, w_mase = candidate.get("mase"), winner.get("mase")
    if c_mase is None or w_mase is None or not np.isfinite(c_mase):
        return f"{name} produced unusable validation results."
    if w_mase and w_mase > 0:
        pct = (c_mase - w_mase) / w_mase * 100
    else:
        pct = float("inf") if c_mase > 0 else 0.0

    hint = ""
    trend = meta.get("trend_strength") or 0.0
    seasonal = meta.get("seasonality_strength") or 0.0
    if name in TREND_FAMILY and trend < 0.3:
        hint = " — it assumes a trend the series does not sustain"
    elif name in SEASONAL_FAMILY and seasonal < 0.3:
        hint = " — there is no stable repeating pattern for it to exploit"
    elif name in LEVEL_FAMILY and trend > 0.6:
        hint = " — it could not track the series' trend"
    elif name == "Naive":
        hint = " — carrying the last value forward validated worse"
    elif name in CONTEXT_FAMILY:
        hint = (" — the operating conditions of a period explain less about "
                "this material than its own recent history does")

    if pct <= 0.0:
        return (f"{name} validated as well as the winner but was not chosen "
                "on the tie-break (stability, then simplicity).")
    if not np.isfinite(pct):
        return f"{name} was rejected — its validation error was far higher{hint}."
    return (f"{name} was rejected — validation error {pct:.0f}% higher than "
            f"the winner{hint}.")


# --- special-case caveats -----------------------------------------------------

def orphan_caveat(line, output_type) -> str:
    return (f"This series has a consumption rate but no driver record for "
            f"output '{output_type}' on line '{line}' exists in any period — "
            "the denominator does not exist. The rate forecast stands, but "
            "demand cannot be reconstructed until a driver is provided or a "
            "planner declares the material independent.")


def declared_mode_note(mode: str, source: str) -> str:
    origin = "the bom sheet" if source == "declared_bom" else "a planner override"
    return (f"Mode is declared {mode} via {origin}; this declaration wins over "
            "whatever the data suggests.")


def low_driver_note(n_excluded: int) -> str:
    return (f"{n_excluded} period(s) were excluded from fitting because the "
            "driver barely ran — a rate divided by a near-zero driver is "
            "noise, not signal.")


def smoothing_bias_caveat(driver_cv: float) -> str:
    return (f"The driver is volatile (CV {driver_cv:.2f}) and smoothing "
            "models cannot weight periods by driver volume; their results may "
            "be biased. The driver-weighted averaging family was kept in the "
            "competition as a cross-check.")


def obsolescence_note() -> str:
    return ("Demand probability is declining period after period; the item "
            "may be phasing out. Consider confirming its status before "
            "committing stock.")
