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

## Getting started in ten seconds

The default workbook is **already loaded** — open **Configure & Run** and
press Run. Nothing needs to be uploaded first.

Every control, chart and table carries a **❓ icon**: hover it to read what
that thing means and how to use it. You should never need this guide open
while working.

## The seven tabs

1. **Overview** — where you are now: how many runs and items exist, a
   download of the sample workbook, and a plain-language guide to every
   forecasting model the engine can choose and when it uses each one.
2. **Data** — the default workbook is preloaded; you can also upload one,
   or point at a path (with a 📂 folder browser). Tabs across the top show
   **Summary**, the **Validation** report, one editable tab per sheet
   (`bom`, `consumption`, `prod`, `consumption_figs`), and **Item modes**.
   - Edit cells directly in the table, add rows with the ➕ row, or delete
     selected rows, then press **💾 Save table**.
   - **Import rows** into any sheet from another file and choose
     **Extend** (append to what is there) or **Replace** (swap the table).
   - Edits are written to *your working copy* — the bundled default file is
     never modified.
   - Orphan items — a rate with no driver ever recorded — appear in red with
     the two ways to resolve them.
3. **Configure & Run** — horizon (3/6/12/24), thresholds, model toggles.
   Press Run; progress shows per stage. Runs are named and kept.
4. **Explorer** — pick items **by description** (the code follows after the
   dash, and searching by code still works). Omit a dimension to combine
   across it; combined rates are always driver-weighted. A single item shows
   its code, description, line and output type, then: the chart with 80%/95%
   bands and driver overlay, the intelligence card, the full model
   competition, why the winner won and why each loser lost, and the override
   control.
   - For a **Relative** item the chart shows the **consumption rate
     (`cons_rate`)** by default — that is what the engine actually models.
     Switch to *Reconstructed demand* to see rate × planned production.
   - For an **Absolute** item the chart shows consumption quantity.
5. **Portfolio** — the triage screen. Badges tell you where to spend your
   attention: data-quality issues first, then structural changes, declining
   accuracy, manual reviews. Everything else is "automatic OK".
6. **Accuracy** — after a few months, import newer actuals (upload or 📂
   browse). The engine compares what it predicted with what happened, tracks
   error over time and raises drift alerts.
7. **Export** — Excel/CSV of anything you see. Every exported row carries
   item code, description, line and output type as separate columns.

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
