# ForecastLens — Planner's Guide

## What it does

ForecastLens reads your consumption history, works out how each material
behaves, lets multiple forecasting methods compete under honest back-testing,
picks a winner per material, and tells you — in plain language — why.

You never have to touch a terminal: load a workbook, press Run, read results.

## The workbook

Four sheets (only the first two are mandatory):

| Sheet | What it holds |
|---|---|
| `bom` | Item master: codes, descriptions, units, categories. Optional `mode` column to declare a material dependent/independent. |
| `consumption` | History: date, item, quantities, optional consumption rate. |
| `prod` | The driver (production output, cases, orders…). May be absent entirely for trading/e-commerce businesses. |
| `consumption_figs` | Engineered standard rates, if you have them. |

## Absolute vs Relative — what "mode" means

- **Relative**: consumption depends on a driver (e.g. kg of additive per ton
  produced). The engine forecasts the *rate* and multiplies by your driver
  plan.
- **Absolute**: consumption is independent (e.g. spare parts, trading goods).
  The engine forecasts the quantity directly, normalized per-day so short
  months don't masquerade as demand drops.

Mode is a property of the material's nature, not of data availability. A
material whose rate history has holes stays Relative — gaps are flagged, not
punished. You can declare a mode explicitly on the Data page; declarations
always win over inference.

## The six pages

1. **Data** — load and validate. Read the report top-down: fatal (blocks the
   run), warnings (run proceeds, data flagged), info. Orphan series — a rate
   with no driver ever recorded — appear in red with resolution options.
2. **Configure & Run** — horizon (3/6/12/24), thresholds, model toggles.
   Press Run; progress shows per stage. Runs are named and kept.
3. **Explorer** — pick any material/line/output combination. Omit a dimension
   to combine across it (combined rates are always driver-weighted). A single
   series shows: chart with 80%/95% bands and driver overlay, the
   intelligence card, the full model competition, why the winner won and why
   each loser lost, and the override control.
4. **Portfolio** — the triage screen. Badges tell you where to spend your
   attention: data-quality issues first, then structural changes, declining
   accuracy, manual reviews. Everything else is "automatic OK".
5. **Accuracy** — after a few months, import newer actuals. The engine
   compares what it predicted with what happened, tracks error over time and
   raises drift alerts.
6. **Export** — Excel/CSV of anything you see.

## Reading a forecast

- **Never act on a forecast without its confidence.** Low confidence means
  thin or noisy history — the interval matters more than the point.
- The 80% band says: 8 times out of 10, actual demand lands inside.
- A "standard-rate anchor" winner means your engineered standard is currently
  more credible than anything fitted from history — that is a message, not a
  failure.
- A TSB winner with declining probability suggests the item is phasing out.

## Overrides

If you know something the data doesn't, override the model on the Explorer
page with a reason. The override is locked across future runs until you clear
it. The competition table stays visible so you can check your choice against
the evidence at any time.
