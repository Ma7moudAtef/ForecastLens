"""What every column of the results workbook means, and why a planner cares.

One source of truth for two places: the `data_dictionary` sheet written into
the downloaded workbook, and the per-column ❓ tooltips in the app's export
preview. If a column is added to an export sheet and not described here,
`tests/unit/test_export_guide.py` fails the build — an undocumented column in
a file a planner has to act on is a defect, not an omission.

Each entry is (what it is, why you need it). Kept in planner language: no
MASE, no p-values, no internal identifiers.
"""
from __future__ import annotations

import pandas as pd

#: columns that identify the row, present on every sheet
IDENTITY_GUIDE: dict[str, tuple[str, str]] = {
    "item_code": (
        "The material's code, exactly as it appears in your workbook.",
        "The key you join back to your own systems — ERP, purchasing, stock."),
    "description": (
        "The material's name, taken from the bom sheet. Reads "
        "'(not in bom)' when the item has no bom row at all.",
        "So a row is readable without looking anything up. Any '(not in "
        "bom)' is a gap in your master data worth closing — those items also "
        "cannot borrow behaviour from category siblings."),
    "line": (
        "The production line the row belongs to.",
        "Consumption is forecast per line: the same material on two lines is "
        "two different behaviours, and mixing them hides both."),
    "output_type": (
        "The product or output the row belongs to.",
        "Same reason as the line — a material used for two outputs consumes "
        "differently for each."),
    "run_id": (
        "Internal identifier of the forecast run that produced the row.",
        "Only needed when you compare two exports and want to be certain "
        "which run each came from."),
}

SHEET_PURPOSE: dict[str, str] = {
    "data_dictionary": (
        "This sheet. What every column on every other sheet means and why it "
        "is there."),
    "forecasts": (
        "The numbers. One row per material, line, output and future period — "
        "this is what you plan and buy against."),
    "selections": (
        "Which method was chosen for each material and why, in plain "
        "language. Read this before trusting a number that surprises you."),
    "series": (
        "What the engine worked out about each material's behaviour: how "
        "much usable history it has, how predictable it is, whether its "
        "pattern changed."),
    "context": (
        "Whether a material's consumption depends on the operating "
        "conditions of the period — how many lines ran, which ran together, "
        "whether a promotion was on."),
    "warnings": (
        "Everything the engine found wrong or worth questioning in the input "
        "data. Fixing these is the cheapest way to improve a forecast."),
}

FORECASTS_GUIDE: dict[str, tuple[str, str]] = {
    "period": (
        "The future period the row forecasts.",
        "Line it up with your planning calendar."),
    "target_value": (
        "The forecast on the scale the engine actually modelled: a "
        "consumption RATE for a Relative material, a per-day quantity for an "
        "Absolute one.",
        "The honest output of the model. For a Relative material this is the "
        "number to challenge — the demand below is this multiplied by your "
        "own production plan."),
    "lower_80": (
        "Bottom of the 80% range for target_value.",
        "Four periods in five should land above this. Use it when you want "
        "the optimistic-but-not-reckless case."),
    "upper_80": (
        "Top of the 80% range for target_value.",
        "The everyday planning ceiling: cover to here and you are right four "
        "times in five."),
    "lower_95": (
        "Bottom of the 95% range for target_value.",
        "The near-worst case on the low side — useful when overstocking is "
        "what hurts."),
    "upper_95": (
        "Top of the 95% range for target_value.",
        "The safety-stock number for a material you cannot afford to run out "
        "of."),
    "driver_plan": (
        "Your own planned production for that period, line and output, taken "
        "from the prod sheet. Empty for Absolute materials, which do not "
        "depend on one.",
        "The multiplier behind reconstructed_demand. If this is wrong the "
        "demand is wrong, however good the rate is — check it first when a "
        "number looks off."),
    "reconstructed_demand": (
        "Expected consumption in units: the forecast rate multiplied by "
        "driver_plan (Relative), or the per-day forecast multiplied by the "
        "days in the period (Absolute). Empty when no production plan covers "
        "the period.",
        "The quantity you actually order. An empty cell means the plan does "
        "not reach that far — extend the plan rather than guessing."),
    "demand_lower_80": (
        "Bottom of the 80% range for reconstructed_demand.",
        "The demand range in units, for planners who work in quantities "
        "rather than rates."),
    "demand_upper_80": (
        "Top of the 80% range for reconstructed_demand.",
        "The usual cover level in units."),
    "demand_lower_95": (
        "Bottom of the 95% range for reconstructed_demand.",
        "Near-worst case on the low side, in units."),
    "demand_upper_95": (
        "Top of the 95% range for reconstructed_demand.",
        "The safety-stock quantity for a critical material."),
    "confidence": (
        "How much to trust this row, 0 to 1. It blends back-tested accuracy "
        "with how much usable history exists, how predictable the material "
        "is, and data quality.",
        "Stops a short, flattering-looking series being trusted like a long "
        "well-behaved one. Sort by it to find where your attention is worth "
        "most."),
}

SELECTIONS_GUIDE: dict[str, tuple[str, str]] = {
    "model_name": (
        "The forecasting method chosen for this material.",
        "Different methods imply different assumptions. Seeing "
        "'SeasonalNaive' on a material you thought was flat is a useful "
        "surprise."),
    "window": (
        "How many recent periods the method looks back over, when it uses a "
        "window. Empty means it uses all available history.",
        "A short window means the engine judged older history no longer "
        "representative — often a sign something changed."),
    "mase": (
        "Validation error from repeated back-testing: the forecast was made "
        "with only the earlier data and scored against what actually "
        "happened. Below 1 beats simply repeating last period.",
        "The one number that says whether the method earned its place. "
        "Anything above 1 means a naive guess would have done as well."),
    "confidence": (
        "The same 0-1 trust score as on the forecasts sheet.",
        "Triage: work through low-confidence materials first."),
    "confidence_label": (
        "That score as low / medium / high.",
        "For filtering and sorting without thinking about the decimals."),
    "route": (
        "How the method was arrived at: a full competition, a routed "
        "sporadic-demand family, or the cold-start ladder for materials with "
        "too little history.",
        "Tells you whether the number came from a real contest or from a "
        "fallback. Cold-start rows deserve a human look."),
    "reason_code": (
        "A short machine-readable tag for that decision.",
        "For filtering a large export — group by it to see every cold-start "
        "material at once."),
    "reason_text": (
        "The decision written out in plain language: why this method won and "
        "what it assumes.",
        "The column to read when you disagree with a forecast. It usually "
        "explains itself in one sentence."),
    "is_override": (
        "1 when you locked this method yourself, 0 when the engine chose it.",
        "Your own decisions stay visible and auditable across runs."),
    "override_reason": (
        "The reason you recorded when locking the method.",
        "So a decision made months ago can still be understood — by you or "
        "by whoever takes over."),
}

SERIES_GUIDE: dict[str, tuple[str, str]] = {
    "mode": (
        "Relative = consumption depends on a production driver, so the "
        "engine forecasts a rate. Absolute = it does not, so the engine "
        "forecasts quantity directly.",
        "Decides what the forecast columns actually mean. A material in the "
        "wrong mode is the single biggest source of nonsense output."),
    "mode_source": (
        "Where that mode came from: inferred from the data, declared in the "
        "bom sheet, or declared by you in the app.",
        "Shows whether the engine guessed or you decided. If an inferred "
        "mode is wrong, declare it — a declaration always wins."),
    "target_uom": (
        "The unit the modelled value is expressed in.",
        "Guards against comparing a kg-per-tonne rate with a tonne-per-tonne "
        "one."),
    "first_period": (
        "First period with recorded history.",
        "How far back the evidence goes."),
    "last_period": (
        "Last period with recorded history.",
        "A last_period well before the others means the material stopped "
        "moving — worth checking whether it is being phased out."),
    "n_periods": (
        "Length of the span from first to last period, gaps included.",
        "Compare with n_observed to see how patchy the history is."),
    "n_observed": (
        "Periods that carry a real observation.",
        "The actual evidence behind the forecast, as opposed to the calendar "
        "span."),
    "n_reliable": (
        "Periods usable for fitting. Excludes periods whose production was "
        "so low that a rate against it would be noise.",
        "The number that decides which methods were even allowed to compete. "
        "Fewer than six and the material falls back to the cold-start "
        "ladder."),
    "n_applicable": (
        "Periods where the line actually ran. A period with no consumption "
        "AND no production is not a zero — there was nothing to consume "
        "against.",
        "Stops a shutdown making a steady material look sporadic. A big gap "
        "between this and n_periods usually means a plant stoppage."),
    "is_orphan": (
        "1 when the material has a consumption rate but no production record "
        "for its line and output in any period.",
        "The rate forecast still stands, but demand in units cannot be "
        "calculated at all until the production data or the mode is fixed. "
        "Always worth resolving."),
    "pattern_class": (
        "How demand behaves: smooth, erratic, intermittent (many zero "
        "periods) or lumpy (rare and variable).",
        "Sets expectations. Nobody forecasts a lumpy material accurately; "
        "the right response is buffer stock, not a better model."),
    "adi": (
        "Average number of periods between movements.",
        "1 means it moves every period. 5 means it moves roughly twice a "
        "year — a very different ordering problem."),
    "cv2": (
        "Squared variability of the sizes when it does move.",
        "High means the quantity jumps around even when the material is "
        "used. Together with adi it explains the pattern class."),
    "trend_strength": (
        "How much of the movement is a sustained direction, 0 to 1.",
        "High values justify planning for growth or decline rather than a "
        "flat level."),
    "seasonality_strength": (
        "How much of the movement is a repeating annual pattern, 0 to 1.",
        "High values mean timing matters as much as volume."),
    "stationary": (
        "1 when the level is statistically stable over time.",
        "A 0 warns that the average has shifted, so an average of all "
        "history is misleading."),
    "autocorr_lag1": (
        "How strongly a period resembles the one before it.",
        "Near zero means the past tells you very little and even a good "
        "forecast will be wide."),
    "outlier_pct": (
        "Share of periods that are extreme relative to the rest.",
        "A high value is usually a data problem — a unit mix-up or a "
        "one-off — and worth checking before trusting the forecast."),
    "missing_pct": (
        "Share of the span with no observation.",
        "Tells you how much of the history was filled in rather than "
        "recorded."),
    "structural_break_period": (
        "The period around which the material's behaviour appears to have "
        "changed. Empty when nothing changed.",
        "Something real happened then — a recipe change, a new supplier, a "
        "line rebuild. History before that point may no longer apply."),
    "forecastability": (
        "How predictable the material is in principle, 0 to 1.",
        "A low score is not a bad model, it is a hard material. Manage it "
        "with stock, not with expectations."),
    "data_quality": (
        "How complete and clean this material's input data is, 0 to 1.",
        "The one score you can actually improve yourself, and the cheapest "
        "way to get a better forecast."),
}

CONTEXT_GUIDE: dict[str, tuple[str, str]] = {
    "tested": (
        "1 when there were enough differing operating conditions to compare.",
        "A 0 means the question could not be asked — usually only one "
        "operating pattern ever occurred."),
    "n_regimes": (
        "How many distinct operating conditions this material has run under "
        "— one line alone, two together, a promotion week, and so on.",
        "Shows how varied the evidence is. One condition means there is "
        "nothing to compare."),
    "n_observations": (
        "Periods that went into that comparison.",
        "A comparison across eight periods deserves less weight than one "
        "across thirty."),
    "p_value": (
        "How likely the difference between conditions is just chance. Below "
        "0.05 counts as real.",
        "Guards against reading a pattern into normal variation."),
    "effect_size": (
        "How much of the material's variation the operating conditions "
        "explain, 0 to 1.",
        "Separates 'real but tiny' from 'real and worth acting on'."),
    "spread_pct": (
        "How much higher consumption runs under the heaviest condition than "
        "under the lightest, relative to this material's own average.",
        "The number to act on. 0.40 means it runs 40% heavier when the plant "
        "is in its busiest configuration."),
    "material": (
        "1 when the effect is both statistically real and large enough to "
        "matter (10% by default).",
        "Only these materials were allowed context-aware models. The rest "
        "are better forecast from their own history."),
    "verdict": (
        "The finding in one sentence.",
        "The whole column in readable form — start here."),
    "skip_reason": (
        "Why no comparison was possible, when there was none.",
        "Tells you whether it is a data gap you could close or simply the "
        "shape of your operation."),
}

WARNINGS_GUIDE: dict[str, tuple[str, str]] = {
    "code": (
        "Short tag for the kind of problem.",
        "Group by it to see how many materials share one root cause — "
        "fixing that one cause often clears hundreds of rows."),
    "severity": (
        "How serious: info, warning, or fatal.",
        "Work down from fatal. A fatal issue stops the run entirely."),
    "count": (
        "How many rows, periods or items the issue covers.",
        "Tells you whether it is a stray cell or a systemic gap."),
    "message": (
        "The problem in plain language, naming what is affected.",
        "Usually contains the fix. This is the sheet to work through when "
        "you want a better forecast without changing anything else."),
}

#: sheet -> {column: (what it is, why you need it)}
COLUMN_GUIDE: dict[str, dict[str, tuple[str, str]]] = {
    "forecasts": {**IDENTITY_GUIDE, **FORECASTS_GUIDE},
    "selections": {**IDENTITY_GUIDE, **SELECTIONS_GUIDE},
    "series": {**IDENTITY_GUIDE, **SERIES_GUIDE},
    "context": {**IDENTITY_GUIDE, **CONTEXT_GUIDE},
    "warnings": {**IDENTITY_GUIDE, **WARNINGS_GUIDE},
}

DICTIONARY_SHEET = "data_dictionary"


def describe_column(sheet: str, column: str) -> tuple[str, str]:
    """(what it is, why you need it) for one column, empty when unknown."""
    return COLUMN_GUIDE.get(sheet, {}).get(column, ("", ""))


def tooltip(sheet: str, column: str) -> str:
    """One string for a ❓ hover: what the column is, then why it matters."""
    what, why = describe_column(sheet, column)
    if not what:
        return ""
    return f"{what}  →  {why}" if why else what


def guide_frame(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """The data_dictionary sheet, covering exactly the sheets being exported
    and the columns they actually carry — in the order they appear, so a
    reader can follow it left to right against the real sheet."""
    rows = []
    for sheet, frame in frames.items():
        if sheet == DICTIONARY_SHEET:
            continue
        purpose = SHEET_PURPOSE.get(sheet, "")
        for column in frame.columns:
            what, why = describe_column(sheet, column)
            rows.append({
                "sheet": sheet,
                "what this sheet is for": purpose,
                "column": column,
                "what it is": what,
                "why you need it": why,
            })
    return pd.DataFrame(rows, columns=["sheet", "what this sheet is for",
                                       "column", "what it is",
                                       "why you need it"])
