# Design Decisions

Decisions locked at project start. Each traces to the build prompt, the
execution plan, or an explicit correction from the project owner.

## D1 — Internal naming: `driver`, never `production`

The word "production" is a steel-industry artifact. The `prod` sheet is the
**driver** table; `production_qty1` maps to `driver_qty` at the ingestion
boundary and the domain word never appears again in `core/` logic, the SQLite
schema, or any internal API. A trading company or online store has no driver
at all — the engine must never assume one exists.

## D2 — ARIMA: included, gated, off by default

ARIMA is implemented, but only offered to series with ≥ 24 periods and only
when explicitly enabled (`models.enable_arima = true`). Automatic order
selection on ~30 points is unstable and rarely beats ETS or Theta while being
much harder to explain.

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

## D6 — Confidential data never enters the repository

`.gitignore` excludes every spreadsheet extension except the whitelisted
`tests/fixtures/sample_public.xlsx`; a pre-commit hook and a CI job
(`scripts/check_spreadsheets.py`) reject anything else. The private dataset is
validated locally only, never in CI, never committed.
