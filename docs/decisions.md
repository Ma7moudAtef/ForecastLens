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

## D10 — How a consumption rate is obtained (three rules)

1. **`cons_rate` supplied → used exactly as given, in the planner's own
   units.** kg per tonne stays kg per tonne; the engine never rescales it and
   never recomputes it from quantities. This is what makes a rate expressed
   as kg/t comparable with itself everywhere in the app.
2. **No `cons_rate`, but driver data exists → the rate may be derived** as
   `consumption ÷ production`, producing units of `item-uom / driver-uom`.
   This is **opt-in** (`rate.derive_missing`, "Derive missing consumption
   rates" on the Configure & Run page), not automatic — see below.
3. **Neither → Absolute mode**, the quantity is forecast directly (per-day
   normalized).

A per-item declared mode still outranks all three.

### Why rule 2 is opt-in rather than automatic

Measured on the sample workbook, deriving rates wherever a driver happens to
exist would reclassify **120 of 121** Absolute items as Relative, and the
derived rate is about **11× more volatile** than the quantity it came from
(median CV 0.851 vs 0.078; worse in 92% of series). The reason is structural:
those materials' consumption does not track output, so dividing a steady
quantity by a driver with CV ≈ 0.97 manufactures noise, and forecasting that
noise then multiplying by the plan is worse than forecasting the quantity.

Making it automatic would also contradict D4: mode would once again depend on
data availability rather than on the material's nature. So the engine flags
the opportunity (`RATE_DERIVABLE` on the Data page) and lets the planner —
who knows whether the material scales with output — decide.

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

## D11 — Context-aware forecasting: one generic capability, never an industry rule

Consumption often depends on the operating conditions of a period and not
only on the series' own history: how many units ran, which of them shared the
plant, how hard they were pushed, whether a promotion or campaign was on. The
engine models that as **one industry-neutral capability**. There is no steel
rule, no FMCG rule, no pharma rule — the same code reads co-running production
lines, co-running store formats and overlapping promotions, because from the
engine's point of view they are the same shape of information.

**Vocabulary** (used everywhere in `core/context/`): `unit` (the thing that
runs), `stream` (what it produces), `driver` (how much), `context` (the
conditions of a period), `regime` (a named combination of conditions),
`co_activity` (what else ran at the same time). The existing `line` /
`output_type` columns map onto `unit` / `stream` at the boundary of the module;
they were not renamed globally, because that would touch the schema, every
view, the exports and the parity fixtures for no behavioural gain.

**Features are derived, not configured.** `core/context/features.py` builds
one row per (period, unit, stream) with `active_set`, `n_active`, `is_solo`,
`co_active_with`, `own_share`, `system_driver`, `utilization`, `mix_entropy`
and a stable `regime_label`. A planner may add anything the driver table
cannot express through an optional `context_calendar` sheet
(`period, unit, stream, factor_name, factor_value`); supplied factors become
ordinary features, and discrete ones join the regime label — a promotion that
is running is part of the operating condition, not something beside it.

**The diagnostic runs for every series, always.** Even where no context model
could ever be fitted, the engine groups the target by regime, tests the
difference (Kruskal-Wallis — non-parametric, honest on small samples),
computes an effect size and the plain percentage spread, and stores the result
in `series_context`. The intelligence card reports it whether or not a context
model was used. "We looked and it does not matter here" is an answer.

**Five guards, and they are the point:**

- **G1 future availability** — every regressor is read from the driver plan,
  which is knowable in advance. `utilization` is scaled by a high-water mark
  computed from *actuals only*, so adding a plan never rewrites the past. If
  the plan does not cover the whole horizon, the models are withheld and the
  card says why.
- **G2 minimum support** — a regime with fewer than `min_regime_obs` (4)
  observations is pooled into an `other` bucket, never fitted on its own and
  never silently deleted.
- **G3 no special treatment** — models 20–22 go through the same rolling-origin
  folds, the same MASE ranking and the same simplicity tie-break as everything
  else. Their static parameter counts are deliberately higher than a moving
  average's, so a near-tie goes to the simpler model.
- **G4 materiality** — significance alone is worthless: on a long history a 2%
  difference is statistically certain. A context model may only compete when
  `p < alpha` **and** the spread between the highest and lowest regime is at
  least `materiality` (10%) of the series' own mean.
- **G5 degrade silently** — a single-unit, single-stream dataset produces
  constant features. The layer detects that, switches itself off, and changes
  no number. No errors, no warnings, no wasted computation.

**What it is not.** It is not a rule that "two lines running means more
consumption" — that is a hypothesis the data has to support per material. It
is not a way to add regressors that must themselves be forecast. It is not a
reason to relax cross-validation. Nothing here changes the atomic grain, the
aggregation rules, or MASE-based selection.

Measured on the sample workbook: 600 of 820 series were testable, 58 showed a
material effect, and 12 were actually won by a context model. That ratio is
the design working — the layer is offered often, believed rarely.

### What the golden regression moved, and why

Adding the layer changed **13 of 820 selections**, all of them for the better
in back-testing (mean validation error 0.87 → 0.52 on the changed series;
none got worse). Twelve went to a context model and one to an ensemble that
now contains one.

The **absolute-mode demand total rose 35%** (1,169 → 1,579). That is not a
scaling bug: eight of the thirteen are Absolute materials whose consumption
tracks total plant activity, and the production plan for the horizon averages
20.6 units of activity against 12.2 in the recorded history. Their forecasts
went up because the plan says the plant will be busier. Relative-mode demand
barely moved (174.8 → 173.8), which is what you would expect — a rate does
not care how much runs.

## D12 — A description column is never blank

An item consumed but absent from the `bom` sheet has no name. Showing an
empty cell for it is the wrong answer twice over: it reads as "the app lost
something", and it hides a gap in the master data that the planner can
actually fix. Every user-facing table routes through `identity.describe()`,
which returns one of exactly three things:

- the real description, when the bom sheet has one;
- `(not in bom)`, when the item is consumed but has no bom row;
- `(not item-specific)`, when the row is not about a single item at all — a
  validation warning covering the whole dataset, say.

The two markers are deliberately different. Conflating them would report a
dataset-level warning as a missing item.

`rule_items_missing_from_bom` is a WARNING rather than INFO for the same
reason: it was quiet enough to be discovered only in a downloaded workbook,
which is the worst place to discover it.

### Why such items are still forecast by default

The strict reading — "not in the master data means it does not exist" — is a
defensible governance rule, and `scope.bom_items_only` implements it
(**Only items listed in the bom sheet** on Configure & Run, `--bom-items-only`
on the CLI). It is **off by default**, because the item's consumption history
is real and forecastable; what is missing is its name and its category, not
its demand.

The sample workbook shows why this must be the planner's choice and not the
engine's: `bom` covers `code1`–`code138`, `consumption` runs to `code259`, and
the 121 items in between are **exactly the 121 Absolute-mode materials**.
Turning the rule on by default would silently delete every Absolute forecast
in the file.

## D13 — The results workbook explains itself

`core/export_guide.py` holds one description per exported column — what it is
and why a planner needs it — and feeds two places from it: the
`data_dictionary` sheet written as the FIRST sheet of the download, and the
per-column ❓ tooltips in the Portfolio preview. `tests/unit/test_export_guide.py`
fails the build if an export sheet grows a column with no entry, because an
undocumented column in a file someone plans against is a defect.

The browser download and `ForecastLens --export` both go through
`export.workbook_bytes()`. The Portfolio page previously assembled its own
`ExcelWriter`, which is how the two could have drifted apart — the dictionary
sheet would have been in one and not the other.

## D14 — A combined Relative view shows its intervals

The combined view charts the driver-weighted mean of the member rates. Its
80% and 95% bounds are that same weighted mean applied to each member's own
rate bounds — not the summed demand bounds divided by something, which is
what an earlier note dismissed as meaningless (correctly).

Because the weights are non-negative and each member bound brackets its own
point estimate, the combined band brackets the combined point estimate. Like
the summed demand bounds, it assumes the members' errors move together, which
makes the band wider rather than narrower. A point estimate with no interval
looks exactly as certain as a single well-behaved series, which is the one
thing an aggregate never is.
