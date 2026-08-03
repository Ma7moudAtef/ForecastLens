# Full System Audit — Phase 0 Findings

**Commit audited:** `9158b07`
**Test suite at time of audit:** 406 passed, 14 skipped (the skips are the
exe-side parity tests, which need `FORECASTLENS_EXE` and a Windows binary).
**No code was changed to produce this report.**

Severity: **P0** wrong numbers · **P1** broken behaviour · **P2**
inconsistency · **P3** cleanliness.

---

## Summary

| ID | Area | Verdict | Severity |
|---|---|---|---|
| C1 | Orphaned accuracy tracking | **Partly present** — table is alive but has no UI writer | P2 |
| C2 | Unit-driven rate formula | **Present, and the biggest finding** | **P0** |
| C3 | Zero vs undefined rate | **Passed** — three states are distinguished | — |
| C4 | Dimension picker semantics | **Conflict with Update 4.6** — needs your decision | P1 (disputed) |
| C5 | Identity columns under aggregation | **Passed** (fixed in `3951dcd`) | — |
| C6 | ARIMA vs ContextRegression | **Premise is factually wrong**; a real count drift exists | P2 |
| C7 | Editable data vs caching | **Two real gaps** (config key, destructive import) | P1 |
| C8 | Single-item runs vs priors | **Passed** | — |
| C9 | Run abort and partial state | Not fully verified — see coverage note | — |
| C10 | Combined-view rate arithmetic | **Deliberate disagreement with the brief** | P2 (disputed) |
| C11 | Overview documentation drift | **Present** — prose is hardcoded | P2 |
| C12 | File browser security | **Present** — no gating, no root restriction | P1 |
| C13 | Tooltip maintainability | **Present** — 87 inline `help=`, no central dictionary | P3 |
| C14 | Sample download / data dictionary | **Partly present** — manual list, not schema-generated | P2 |

**Three findings need your decision before I touch anything: C2, C4, C10.**
Each is a case where this brief and an earlier explicit instruction of yours
point in opposite directions. Per your own rule — *"if two updates genuinely
conflict and both cannot be satisfied, do not choose silently"* — I have set
out both options rather than picking.

---

## C2 — Unit-driven rate formula *(P0, highest priority)*

### What the brief says

> `cons_rate` is **not** one universal formula … `kg/ton` →
> `cons_qty_ton × 1000 ÷ production_qty1`; `pc/heat` →
> `cons_qty_base_uom ÷ production_qty2`.

### What the code does

There is **no unit-resolution function anywhere.** `cons_rate` is taken from
the workbook exactly as supplied and never re-derived
(`core/prep/series_builder.py`), and reconstruction is universally
`rate × driver_qty` (`core/forecast/reconstruct.py:41`).

**`driver_qty2` (`production_qty2`) is mapped at ingestion and then never
read.** Confirmed by grep across `core/` and `app/` — the only two hits are
the schema map and the numeric-coercion set (`core/io/schema.py:58,90`).

### What the sample data actually contains

| `cons_rate_uom` | rows | series | denominator it implies |
|---|---|---|---|
| `p/s` | 5,623 | 242 | `driver_qty2` (uom `s`) |
| `k/t` | 5,260 | 179 | `driver_qty` (uom `t`) |
| `t/d` | 16 | 1 | neither — `d` matches no driver uom |

`driver_uom` is `t`, `driver_uom2` is `s`.

**So 242 of 422 relative series — 57% — carry a rate whose denominator is the
second driver column, and every one of them is currently reconstructed
against the first.** That is a genuine P0: the demand numbers for the
majority of relative series are computed against the wrong denominator.

In *this* sample the two columns happen to be nearly equal (means 0.32317 vs
0.32320), so the error is invisible here. In your real data, where tonnes and
the second measure differ by orders of magnitude, it would not be.

### Was the ÷1000 fixed with a display-layer band-aid?

**No — checked and passed.** The fix (commit `0bc107b`, `docs/decisions.md`
D7) is in `core/forecast/aggregate.py`, in both `aggregate_observations` and
`aggregate_forecasts`. There is no scale multiplier anywhere in `app/`. I
grepped for hardcoded `1000` in the view layer and found none.

### The part I cannot verify, and will not guess

I tested whether the brief's formulas reproduce the supplied `cons_rate` in
the sample. **They do not, and neither does any other combination:**

| family | `qty_base ÷ qty1 ÷ rate` | dispersion |
|---|---|---|
| `k/t` | median 20.5 | p5–p95 = 4.4 … 670, CV 3.8 |
| `p/s` | median 25.1 | p5–p95 = 2.4 … 798, CV 3.8 |

If a fixed formula held, that ratio would be a constant. It varies by two
orders of magnitude. Either the public sample's quantities were
independently rescaled during anonymisation, or `cons_rate` in your source
system is not `quantity ÷ driver` at all.

**This also collides with your own D10 rule 1**, which you specified in an
earlier round: *"if user provided cons rate at certain units of measure, go
by them."* The engine currently honours that. Implementing C2's formulas
would mean **overriding the supplied `cons_rate` with a derived one** — the
opposite instruction.

### Options — your decision

**Option A (recommended, low risk).** Keep the supplied `cons_rate` as
authoritative (D10 rule 1 stands), and fix only the **denominator
selection**: parse `cons_rate_uom`, match its denominator against
`driver_uom` / `driver_uom2`, and reconstruct with the matching column. This
corrects the 242 `p/s` series without contradicting anything you have said,
and needs no formula I cannot verify. One resolver function used by
reconstruction, aggregation and charting. `t/d` would be flagged as
unresolvable rather than silently defaulted.

**Option B (what the brief literally asks).** Add a full unit-resolution
function that *derives* the rate from quantities per unit family, overriding
the supplied `cons_rate`. I would need you to confirm the formulas against
the confidential data first, because I cannot validate them here and the
sample actively contradicts them.

I recommend A, and B only if you confirm the formulas hold in your real
workbook.

---

## C4 — Dimension picker semantics *(P1, disputed)*

The brief's expected table:

| Selection | Brief expects |
|---|---|
| output B, no line | 1 series (lines combined) |
| output B, lines 1 & 2 | **2** |
| outputs B & F, lines 1 & 2 | **4** |

**The code produces 1 in every case.** `app/views/explorer.py:349–351` calls
`aggregate_forecasts(..., group_dims=[])` unconditionally: whatever you
select is filtered, then collapsed into a single combined line.

That is not drift — it is exactly what Update 4.6 asked for:

> *"I have 'what to look at' showing item, line, output then split results by
> then group to chart. They all do the same function. I need to keep the
> first one … remove 'split results by' and 'group to chart', they are just
> confusion to user."*

Splitting by dimension **was** the removed feature. The brief's table
describes the pre-4.6 behaviour.

**Your decision.** (a) Keep 4.6 — selection filters, never splits; the
combined view stays one line. (b) Restore splitting for line/output while
keeping the single control, so selecting two lines draws two series. (b) is
a real usability improvement but re-introduces what you asked me to remove.

*Confirmed passing:* no default selections, and the empty state is meaningful
— nothing selected combines the whole catalogue and says so
(`explorer.py:85`), covered by
`tests/integration/test_ui_smoke.py::test_explorer_default_view_combines_everything`.

---

## C10 — Combined-view rate arithmetic *(P2, disputed)*

The brief asks for `Σ demand ÷ Σ driver`. The code deliberately computes
`Σ(rateᵢ · driverᵢ) ÷ Σ driverᵢ` — the driver-weighted mean of the **recorded
rates** — and documents why at length
(`core/forecast/aggregate.py:120–134`, `docs/decisions.md` D7 and D9).

The reasoning, from the round where you reported the 1000× mismatch: because
`cons_rate` need not equal `qty_base ÷ driver` (C2 above proves it does not
in this data), deriving the combined *history* rate from quantities while the
*forecast* rate is a weighted mean of rates puts the two on different scales
on one chart. That was the actual 1000× bug.

Both are defensible; they answer different questions. The current choice is
the only one that keeps history and forecast comparable. **If C2 Option B is
adopted and `rate` becomes derivable from quantities by definition, the two
formulas converge and this stops mattering.** Until then I recommend leaving
it and would want your explicit instruction to change it.

*Confirmed passing:* the averaging family applies driver weighting in
relative mode — `Σ(wᵢ·rᵢ·Pᵢ) ÷ Σ(wᵢ·Pᵢ)` in
`core/models/averaging.py`, with `tests/traps/test_trap2_driver_weighting.py`
built so an unweighted calculation gives a visibly different answer.

---

## C6 — ARIMA vs ContextRegression *(P2)*

**The brief's premise is factually incorrect, and acting on it would be
harmful.** ContextRegression does **not** use SARIMAX. It is ordinary least
squares via `numpy.linalg.lstsq` with AIC forward selection
(`core/models/context_models.py`). The only statsmodels ARIMA import in the
codebase is inside `core/models/statistical.py:73`, used solely by the ARIMA
model itself.

Stripping ARIMA would therefore **not** break Model 22. I am flagging this
because the brief asks me to write the opposite into the code comments and
docs, which would leave a false statement in the repository.

**A real inconsistency does exist, though:** `ZeroForecast` is a live model —
used by the intermittent router and the cold-start ladder — but is missing
from `ALL_MODEL_NAMES` (`core/models/registry.py:27`). So the registry
reports 22 names while 23 models exist. Any count derived from the registry
is wrong by one. Proposed fix: add it, and exclude it from the UI's
disable-list the same way the other fallbacks are.

**Model count for the record:** 19 originally specified + `ZeroForecast`
(implemented, unlisted) + 3 context = **23**. Not 21. ARIMA is implemented
but gated off by default (D2) — it is not removed from the codebase, only
from the planner-facing options.

---

## C1 — Orphaned accuracy tracking *(P2)*

**Not fully orphaned — the loop is alive but has no UI entry point.**

- Written by: `core/learn/accuracy.py:84`, reachable only through
  `python -m cli.import_actuals`.
- Read by: `app/views/portfolio.py:33` → the *confidence declining* badge.
- Deleted with a run: yes, `accuracy_history` is in `_RUN_TABLES`.

So the table does **not** silently accumulate orphan rows, and the read side
is genuinely used. The gap is that a UI-only user can never populate it, so
that badge can never fire for them. Proposed fix: an "Import actuals" control
on Portfolio next to the badge it feeds, or an explicit note that it is
CLI-only. Low effort either way.

---

## C3 — Zero rate vs undefined rate *(passed)*

All three states are distinguished, and the critical downstream check passes.

| State | Representation | Where |
|---|---|---|
| Real zero (demand occurred, qty 0) | `target = 0`, `is_applicable = 1` | `series_builder.py` |
| Rate undefined (driver 0/missing) | `is_applicable = 0`, excluded | `series_builder.py`, D8 |
| No record | `is_gap_filled = 1` | `series_builder.py` |

**Classification consumes only applicable observations** —
`core/analyze/statistics.py:127–128` filters `is_applicable == 1` *before*
computing ADI and CV², with the comment naming exactly the failure mode the
brief warns about. `tests/unit/test_applicability.py` covers it. This is the
silent high-impact defect the brief asks about, and it is already prevented.

---

## C7 — Editable data vs caching vs determinism *(P1)*

Mostly sound, with two real gaps.

**Passing:** the cache key includes resolved path, `mtime_ns`, size,
granularity, gate thresholds, driver floor and mode overrides, plus a
`CACHE_VERSION` (`app/components/datacache.py:39–56`). Edits write the
working copy, changing `mtime_ns`, so the key changes. Runs are stamped with
`input_hash` (sha256 of the file bytes), so determinism is traceable.

**Gap 1 (P2).** The Data page builds `EngineConfig()` with defaults
(`app/views/data.py:29`), so `rate.derive_missing` is always `False` there.
If a run enables it, the Data page's mode split and series count describe a
different dataset from the one the run produced, and the cache will not
notice. Fix: include `rate.derive_missing` in the fingerprint and surface the
setting on the page.

**Gap 2 (P1, safety).** "Replace — discard existing rows" applies on a single
`Apply import` click (`app/views/data.py:348`). No confirmation, no undo. The
brief explicitly calls for confirmation on this and I agree — it is
destructive and irreversible.

**Not verified:** whether edits force re-validation before a forecast can
start.

---

## C12 — File browser security *(P1)*

`app/components/filebrowser.py` starts at `Path.home()` and walks anywhere
the server process can read. There is **no deployment-mode gate, no allowed
root, and no traversal restriction** — the module docstring acknowledges the
hosted risk in prose and does nothing about it.

Safe in the exe. On Streamlit Community Cloud, which you deploy to, it
exposes the server filesystem to anyone past the shared-secret gate.

Proposed fix: introduce a deployment mode (`local` when frozen or when an
explicit env var says so; `hosted` otherwise), show the browser only in
`local`, and in `hosted` offer upload only. Confine any browsing to a
configured root with `Path.resolve()` containment checks.

---

## C13 — Tooltip maintainability *(P3)*

87 inline `help=` strings across `app/`, no central dictionary. Densest:
`configure_run.py` (24), `data.py` (20), `explorer.py` (13),
`portfolio.py` (12). Coverage of interactive elements is high — the Update
1.5 requirement is met in substance — but the text is unmaintainable in
place: wording cannot be reviewed as a whole and duplicate concepts drift.

Proposed fix: `app/components/help_text.py` with a single dict, referenced by
key, plus a test asserting every interactive element passes a key that
exists.

---

## C11 / C14 — Documentation drift *(P2)*

**C11.** Overview's workflow and model explanations are hardcoded prose
(`app/views/overview.py`). One guard exists —
`test_overview_workflow_matches_the_real_tabs` — comparing tab names against
the router, but nothing ties the model explanations to the registry, so a new
model can be added without appearing on Overview. That happened with the
context models and I updated the prose by hand. Proposed fix: a test that
fails when a registry name has no Overview entry.

**C14.** `DATA_DICTIONARY` in `app/components/samples.py` is a hand-written
list of tuples, not generated from `core/io/schema.py`. It is currently
accurate — I verified every column — but nothing stops it drifting. It does
**not** document the unit-dependent rate formulas, which is exactly the C2
information a user most needs. Proposed fix: derive the column list from the
schema maps, keep the prose descriptions in a dict keyed by internal name,
and fail a test when the two sets differ.

---

## Coverage note — what I have NOT yet examined

Stated plainly so you know the limits of this report:

- **C9** (abort semantics, orphaned joblib workers, run numbering after
  delete) — partly reviewed only. `RunCancelled` discards partial results and
  cancellation is checked between chunks; I did not verify worker termination
  or run-number behaviour after aborts.
- **Phase 2 invariants 1, 4, 5, 6, 7, 9, 10** — I know each is implemented
  and tested, but I did not do the "enforced in exactly one place" analysis
  the brief asks for. Invariants 2, 3 and 8 are confirmed single-site.
- **Phase 3** — the suite passes (406/14 skipped) but I did not diff the
  specific reference numbers against the pre-update baseline, nor audit for
  weakened or deleted tests across the update rounds.
- **Phase 4** — no dead-code sweep, duplication scan, magic-number inventory
  or import-hygiene pass yet.
- **Phase 6** — no UX review yet.

---

## Recommended order, once you have decided

1. **You decide C2 (Option A or B), C4 (a or b), C10 (keep or change).**
2. P0: C2 denominator resolution, with a test covering both unit families.
3. P1: C12 deployment gate, C7 replace-confirmation, C1 accuracy entry point.
4. P2/P3: C6 registry count, C7 cache key, C11/C14 generated docs, C13
   tooltips.
5. Then Phases 2–7 in the brief's order.

I have changed no code. Nothing above is fixed yet.
