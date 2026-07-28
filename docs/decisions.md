# Design Decisions

Decisions locked at project start. Each traces to the build prompt, the
execution plan, or an explicit correction from the project owner.

## D1 — Internal naming: `driver`, never `production`

The word "production" is a steel-industry artifact. The `prod` sheet is the
**driver** table; `production_qty1` maps to `driver_qty` at the ingestion
boundary and the domain word never appears again in `core/` logic, the SQLite
schema, or any internal API. A trading company or online store has no driver
at all — the engine must never assume one exists.

## D2 — ARIMA: implemented, but not a planner-facing option

**Updated after the first UI review.** ARIMA remains implemented and tested
in the model library, but it is no longer exposed in the Run tab and is not
part of any competition by default:

- there is no ARIMA toggle in the UI, and it is absent from the
  "Disable models" list (offering a switch for a model that never competes is
  noise);
- `models.enable_arima` stays in `EngineConfig`, defaulting to `False`, so a
  headless caller (`cli.run --config …`) can still turn it on;
- the gate keeps its ≥ 24-period requirement for when it is enabled.

Rationale, unchanged from the original spec: automatic order selection on ~30
points is unstable, it rarely beats ETS or Theta at this history length, and
it cannot justify itself to a planner in one sentence — which conflicts with
the explainability priority.

## D3 — Inventory policy: out of scope for v1

Safety stock, reorder points, EOQ, replenishment planning and PO generation
are not part of v1. The engine forecasts consumption/demand only. The
`safety_level_days` / `replenishment_level_days` columns were deliberately
removed from the input schema — that removal is the precedent.

## D4 — Mode is permanent (overrides build prompt §6 Step A)

**Correction from the project owner, overriding the 80% driver-coverage rule:**

Mode is a property of the material's nature, not of data availability. If
consumption depends on a driver, the series is Relative and stays Relative —
permanently. Missing driver periods are ordinary data gaps: excluded from
fitting, flagged as warnings, but they never change mode. A Relative series
with too little driver history does NOT flip to Absolute; it falls through the
normal cold-start ladder (standard-rate anchor, then category prior).

- Default inference: `cons_rate` present → Relative; absent → Absolute.
- Optional per-item declared mode: a nullable `mode` column in `bom`, plus a
  UI control. Declared mode always wins over inferred mode.
- There is **no** driver-coverage threshold config value. It was removed
  deliberately; do not reintroduce it.

## D5 — Known data issue: the orphan series

`(code136, line a, output C)` has a consumption rate but no driver record for
output_type C in any period — the combination is absent from the driver sheet
entirely. This is not a gap; the denominator does not exist. The engine
detects it, emits a validation warning naming the series, excludes it from
Relative reconstruction, and surfaces it on the Data page for planner
resolution. It does not guess a denominator and does not delete the series.

## D7 — A combined rate is a driver-weighted mean of recorded rates

When several series are combined, the displayed rate is
`Σ(rateᵢ · driverᵢ) ÷ Σdriverᵢ` — computed from the **recorded rates**, both
for history and for forecasts.

It is deliberately NOT `Σquantity ÷ Σdriver`. `cons_rate` is whatever the
source system defines: per tonne, per day, per a second output measure. It
need not equal `qty_base ÷ driver`, and in the sample workbook it does not
(it is `qty_ton ÷ days`). Deriving the combined history rate from quantities
put history on a different scale from the forecast — 5–50× on the sample
data, 1000× where the unit differs by that factor — so the two could not be
compared on one chart.

**The driver is also counted once per (period, line, output_type), not once
per series.** Production belongs to a line, not to a material: 105 items
consumed on the same line share one production figure, and summing it per
series reported 2,613 tonnes where 26.7 were produced. The weighted mean is
unaffected (the inflation cancels top and bottom), but the displayed driver
total and the chart overlay were wrong.

## D9 — The combined rate table shows production, not a derivable ratio

In a combined view the displayed `rate` is the driver-weighted **mean** of
the member rates, while `driver_plan` / `driver_qty` is the real production
counted once. Those two columns therefore do **not** satisfy
`rate == demand ÷ driver` when several items share a line: `demand` is the
sum across items, so dividing it by one line's production gives the basket's
total consumption per unit of output, not the average member rate.

Both numbers are correct and both are useful; they answer different
questions. The help text on the page says which is which. The weighted mean
is what the chart plots, because it is the only definition that is
comparable between history and forecast and that survives mixed units across
items.

## D8 — Zero rate with zero driver is "the line did not run"

A period with no consumption rate **and** no production is not a zero-demand
observation: the denominator does not exist, so a per-unit-of-output rate has
no meaning there. Such periods are marked `is_applicable = 0` and are
excluded from demand-pattern classification and from fitting (their driver
carries no weight in any weighted average).

Without this, a four-month plant shutdown turns a perfectly smooth material
into an "intermittent" one and drags its average down. A zero rate while the
line *was* running is a genuine zero and still counts.

## D6 — Confidential data never enters the repository

`.gitignore` excludes every spreadsheet extension except the whitelisted
`tests/fixtures/sample_public.xlsx`; a pre-commit hook and a CI job
(`scripts/check_spreadsheets.py`) reject anything else. The private dataset is
validated locally only, never in CI, never committed.
