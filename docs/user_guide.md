# ForecastLens — Planner's Guide

## What it does

ForecastLens reads your consumption history, works out how each material
behaves, lets multiple forecasting methods compete under honest back-testing,
picks a winner per material, and tells you — in plain language — why.

You never have to touch a terminal: load a workbook, press Run, read results.

## The workbook

Five sheets (only the first two are mandatory):

| Sheet | What it holds |
|---|---|
| `bom` | Item master: codes, descriptions, units, categories. Optional `mode` column to declare a material dependent/independent. |
| `consumption` | History: date, item, quantities, optional consumption rate. |
| `prod` | The driver (production output, cases, orders…). May be absent entirely for trading/e-commerce businesses. |
| `consumption_figs` | Engineered standard rates, if you have them. |
| `context_calendar` | Optional. Things you know in advance that the driver table cannot express: promotions, campaigns, shutdowns, recipe changes. Columns: `period`, `factor_name`, `factor_value`, and optionally `unit` and `stream`. |

### The context calendar

One row per factor per period. Leave `unit` and `stream` blank for something
that applies plant-wide. `factor_value` may be a number (`0`/`1` for on/off,
or any measurement) or text (`recipe = A`), and text becomes one indicator per
distinct value.

| period | factor_name | factor_value | unit | stream |
|---|---|---|---|---|
| 2024-03 | promotion | 1 | | |
| 2024-04 | promotion | 0 | | |
| 2024-05 | campaign | 1 | line_a | |

Fill in **future** periods too. The engine only uses a factor it can read for
the periods it is forecasting — a promotion you record only in history is
history, not a forecasting input.

## When a consumption rate has nothing to divide by

An item can carry a `cons_rate` for a line and output type that **never
appears in the `prod` sheet at all**. That is not a gap in the history — the
denominator does not exist, and no amount of extra history will create it. A
rate forecast for such a series could never be turned into a quantity, so the
engine sets the rate aside and forecasts its **consumption quantity directly**
(Absolute mode). Its `mode_source` reads `no_driver`, the Data page lists it,
and the validation report explains it.

Nothing is guessed and nothing is deleted. Add production rows for that line
and output and the series goes back to being forecast as a rate on the next
run — the mode is worked out from your current data every time.

This applies only when the combination is missing **entirely**. A material
whose production data has a few missing months keeps its mode: those are
ordinary data gaps, excluded from fitting and flagged, never a reason to
change what a material fundamentally is.

## Periods when the line did not run

If a material has no consumption rate in a period **and** there was no
production on that line and output, the engine treats the period as "not
applicable" rather than as zero demand — there was nothing to consume
against. Those periods are left out of the demand-pattern classification and
out of fitting, so a plant shutdown cannot make a steady material look
sporadic. A zero recorded while the line *was* running is a real zero and
still counts.

## Where the consumption rate comes from

| Your data | What the engine does |
|---|---|
| `cons_rate` supplied | Uses it **exactly as given, in your units** — kg per tonne stays kg per tonne. It is never rescaled or recomputed from quantities. |
| No `cons_rate`, but production data exists | Treated as Absolute by default. Switch on **Derive missing consumption rates** (Configure & Run) to have the engine work it out as consumption ÷ production instead. |
| No `cons_rate` and no production data | Absolute — the quantity is forecast directly. |

A mode you declare for an item always beats all three.

**Why deriving is off by default.** A missing rate usually means the material
is not driver-dependent. Dividing a steady consumption quantity by a variable
production figure manufactures volatility — on the sample data the derived
rate is around 11× more variable than the quantity it came from — so
forecasting the quantity directly is more accurate for those items. The Data
page tells you how many items *could* be derived, so the choice is yours and
not the engine's.

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

## The five tabs

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
   - Whichever source you pick stays picked until you change it; saving an
     edit moves you to your working copy.
   - Reading and validating a workbook is **cached on disk**, so reopening
     the app is instant instead of re-reading everything. The cache is keyed
     to the file, the analysis settings and your mode declarations, so it can
     never serve a stale picture; **↻ Re-read file** forces a fresh pass.
   - Orphan items — a rate with no driver ever recorded — appear in red with
     the two ways to resolve them.
3. **Configure & Run** — choose the **scope** first: all materials, a single
   item, or a list of items (picked by description). A scoped run is far
   faster and is judged exactly the same way — the engine still studies the
   full dataset, so cold-start items keep borrowing behaviour from all their
   category siblings; only forecasting is restricted. Then set the horizon,
   thresholds and lookback windows — all of them + / − steppers you can dial
   to any value — and press Run. The moving-average windows actually tried
   are listed under the settings before you launch.
   - Runs appear as **Run 1, Run 2, …** with their date and what they
     covered. Every run is kept, so you can switch back at any time; items a
     run did not cover keep the results of the run that last included them.
   - While a run is going you see a **live log** of every stage (rows
     loaded, series built, demand patterns found, chunks forecast with an
     ETA, models chosen) and an **⛔ Abort run** button. Aborting stops after
     the chunk in flight and saves nothing — earlier runs are untouched. The
     log stays available afterwards and can be downloaded.
   - The **Previous runs** section lists them all and lets you **delete a
     single run** or **clear the whole history** (tick the confirmation box
     first). Deleting removes that run's forecasts, model choices and
     warnings — your data, model overrides and mode declarations are kept.
     Run numbers are never reused or shifted; clearing everything restarts
     numbering at 1.
4. **Explorer** — one control decides everything: pick items **by
   description** (the code follows after the dash; searching by code still
   works), plus optionally lines and output types. Nothing is preselected.
   Whatever you leave empty is combined across — no line selected means all
   lines added together. Narrow it to a single item, line and output and the
   view switches to that series in full: its code, description, line and
   output type, the chart with 80%/95% bands and driver overlay, the
   intelligence card, the model competition, why the winner won and why each
   loser lost, and the override control.
   - For a **Relative** item the chart shows the **consumption rate
     (`cons_rate`)** by default — that is what the engine actually models.
     Switch to *Reconstructed demand* to see rate × planned production.
   - For an **Absolute** item the chart shows consumption quantity.
   - In the **combined view** the same rule holds: Relative selections are
     charted as a consumption rate, Absolute selections as consumption
     quantity. If your selection mixes both, a **Show** switch appears: a
     rate and a quantity are different units and cannot share an axis.
   - A combined rate is the **driver-weighted average of the recorded
     rates** — each period's rate counts in proportion to the production it
     was consumed against. History and forecast are computed the same way,
     so they sit on one scale and are directly comparable. The driver shown
     is the real production for the line, counted once, not once per item.
   - The intelligence card also reports **operating context** for every
     item: whether its consumption really does change with what else the
     plant is doing, by how much, and under which conditions it has actually
     run. This appears even when the answer is "it makes no difference here"
     — that is worth knowing too.
5. **Portfolio & Export** — the triage screen. Badges tell you where to
   spend your attention: data-quality issues first, then structural changes,
   declining accuracy, manual reviews. Everything else is "automatic OK".
   The same page exports the results: the filtered table as CSV, or the full
   Excel workbook (forecasts, selections, series profiles, operating context,
   warnings). Every exported row carries item code, description, line and
   output type as separate columns.
   - **Look inside before you download.** Below the download buttons every
     sheet of the workbook is shown exactly as it will be exported, one tab
     each. Hover the ❓ on any column heading to see what it holds and why you
     would use it.
   - The workbook's **first sheet is a `data_dictionary`** carrying that same
     explanation for every column of every sheet, so the file explains itself
     to whoever you send it to.
   - Every sheet arrives as a **proper Excel table**: banded rows, filter
     buttons on each heading, the heading row frozen so it stays put while
     you scroll, columns sized to their contents, long prose wrapped rather
     than stretched, and numbers with a sensible number of decimals. The
     sample workbook and your saved working copy are formatted the same way.

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

## Tracking accuracy against actuals

Forecast-vs-actual tracking is not one of the app's tabs. The engine still
does it, from the command line:

```bash
python -m cli.import_actuals --input newer_data.xlsx --db forecastlens.db
```

This compares the latest run's forecasts with what actually happened, records
the error per period, and flags series whose accuracy is drifting. That
history feeds the Portfolio page's *confidence declining* badge.

## When consumption depends on what else is running

Some materials do not depend only on their own past. A line that runs alongside
another may consume more per tonne; a promotion week may lift usage across the
board; a unit running at a quarter of its normal rate still needs its standing
cleaning and heating, so its consumption *per unit of output* goes up.

The engine works those conditions out for itself from the `prod` sheet — which
units ran, which shared the plant, how hard each was pushed, how evenly output
was spread — and adds anything you supply through the `context_calendar` sheet.
Every item is then tested for whether its consumption actually differs between
those conditions, and the answer appears on its intelligence card.

Three extra models become available to an item only when the effect is both
real and large enough to matter (10% by default, adjustable on Configure &
Run):

- **Fixed+Variable** — separates the standing consumption from the part that
  scales with output. This is the model that explains why a rate rises when a
  line runs slowly.
- **Regime-Conditional** — a separate level per operating pattern, applied
  according to what the plan says each future period will be.
- **Context Regression** — a small regression on the period's conditions, at
  most one factor per eight periods of history.

They then have to win the same back-test as every other model. On the sample
dataset 58 of 820 items showed a material effect and 12 were actually
forecast with a context model — the rest were better served by their own
history, and the engine says so.

**What this needs from you:** a production **plan** covering the whole
horizon. Every context factor is read from the plan, because a forecasting
input has to be known before the period happens. Without a plan for a period,
the engine will not guess the conditions — it withholds these models and tells
you why on the card.

If your data has one line and one output type there is nothing here to learn,
and the whole layer switches itself off without changing a single number.

## Items that are not in your bom sheet

An item can appear in `consumption` without having a row in `bom`. When that
happens the engine has no name and no category for it, so:

- every table and every exported sheet shows **`(not in bom)`** where the
  description would be — never a blank cell, because a blank looks like the
  app lost something rather than like your master data is incomplete;
- a cold-start series for that item cannot borrow behaviour from category
  siblings and falls further down the fallback ladder;
- the Data page reports the count under **ITEM_NOT_IN_BOM**.

Its consumption history is still real, so **by default the item is still
forecast**. If your rule is "if it is not in the master data it does not
exist", switch on **Only items listed in the bom sheet** on Configure & Run
(or pass `--bom-items-only` to the CLI) and those items are left out of the
run entirely.

Check the count before you do. On the bundled sample workbook the bom sheet
covers `code1`–`code138` while consumption runs to `code259`, so the switch
would drop **121 of 248 items** — every Absolute-mode material in the file.
The fix that loses nothing is to complete the bom sheet.
