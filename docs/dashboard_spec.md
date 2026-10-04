# Dashboard layer — design spec and build sequence

Status: **spec only, nothing built.** Numbers below were read out of the live
warehouse on 2026-10-03, not estimated.

---

## 1. The question this answers, and the one it refuses

The customer's question was *"which of our cost **lines** are exposed"* — plural.
Everything built so far answers it one role at a time. That is the gap the
dashboard fills, and it is the only justification for building one.

**The dashboard is a portfolio view, not a metrics dashboard.** The distinction is
load-bearing, because a conventional KPI grid is precisely what this
architecture refuses: numbers lifted away from their reasoning, laid side by side,
inviting comparison between quantities that must not be compared. Every refusal
the project already enforces survives into the dashboard or the dashboard does not
ship:

- Exposure and lag stay separate quantities. No combined score, no "AI risk index".
- Every figure traces to a hashed source, including chart geometry.
- The brand red never encodes data.
- A figure the registry cannot provenance is not drawn.

---

## 2. What the data actually supports

Four findings from inspecting the warehouse. Three of them constrain the design
more than any aesthetic choice does.

### 2.1 The cohort gives a real portfolio spread

Twelve SOC 13-2\* occupations, 231 tasks, exposure 0.397 to 0.703 under one
classifier. That is a 30-point spread with no saturation at either end, which is
what makes a ranking chart worth drawing at all.

| Occupation | Index | Tasks |
|---|---|---|
| Tax Preparers | 0.703 | 12 |
| Loan Officers | 0.642 | 30 |
| Insurance Underwriters | 0.627 | 7 |
| Credit Analysts | 0.626 | 11 |
| Tax Examiners and Revenue Agents | 0.612 | 21 |
| Credit Counselors | 0.598 | 23 |
| Accountants and Auditors | 0.570 | 29 |
| Budget Analysts | 0.543 | 13 |
| Personal Financial Advisors | 0.501 | 21 |
| Financial Examiners | 0.404 | 17 |
| Financial Quantitative Analysts | 0.404 | 21 |
| Financial and Investment Analysts | 0.397 | 26 |

### 2.2 The lag does not vary by occupation, and the design must not imply it does

All 30 persisted verdicts carry the identical interval: **p10 5.0 / p50 10.1 /
p90 30.0**. That is correct rather than a bug — the lag is estimated from
sector-level adoption evidence (NAICS 52), so it is one quantity for the whole
finance family, not twelve.

**Consequence:** the lag may never be a per-role bar, series, column, or sort key.
It appears exactly once, as a single page-level figure. A dashboard showing twelve
roles against twelve lag bars would be inventing variation that does not exist,
and it is the first thing a naive build would get wrong.

### 2.3 Only three of twelve roles can be drilled into

| | Occupations |
|---|---|
| Full persisted run (verdict + task scores + source bindings) | **3** — Financial and Investment Analysts (26 runs), Tax Preparers (3), Loan Officers (1) |
| Cohort index only — one number, no task detail, no caveats, no bindings | **9** |

So the ranking chart can show twelve and open three. This has to be visible in the
UI rather than discovered by clicking, and it forces an explicit choice (§7.1).

There is a second, sharper reason not to paper over it: a cohort index and a run's
exposure index come from different provenance paths. The same occupation has
produced 0.391, 0.397, 0.452 and 0.479 across runs and classifiers. Drawing a
cohort value and a run value on one axis would mix two chains and present them as
one series.

### 2.4 The adoption curve is a genuine time series

Twenty-one biweekly observations per question, June 2025 to April 2026, for NAICS
sector 52:

- Question 7 — firms currently using AI to produce goods or services
- Question 24 — firms expecting to use AI within six months

Two series, 21 points each, ~30% to ~37%. This is the only true
change-over-time data in the warehouse, and the only chart that earns a line.

---

## 3. The KPI contract

A tile earns its place only if the figure registry can produce the number. That
rule already exists for the report and extends here unchanged.

| Tile | Value today | Source | Why a client needs it |
|---|---|---|---|
| **Roles assessed** | 12 | `core.task` count | Scope of the answer |
| **Tasks assessed** | 231 | `core.task` count | Depth of the answer |
| **Hero: tasks judged outright replaceable** | **0 of 26, across 1 of 12 roles** — *corrected in W10, see below* | `score.task_score.direction` | The headline finding, and the one that changes a hiring plan |
| **Exposure range across the family** | 0.40 – 0.70 | `score.cohort_index` | Shows the rubric discriminates |
| **Most / least exposed** | Tax Preparers / Financial Analysts | ranking | Where to look first |
| **Years before the cost line moves** | 10.1 (5.0 – 30.0) | `score.role_verdict` | Page-level, stated once |
| **Figures traced** | per-run count | traceability walk | The standing of everything above |

Deliberately **not** tiles: any average of exposure across roles (an unweighted
mean over twelve occupations of different headcount is not a quantity anyone
employs), any percentage "at risk", any single confidence score, and the
calibration delta on its own (§4.3 explains why it needs its own chart).

### 3.1 Correction from W10: the hero figure is not yet a portfolio claim

The table above originally proposed **"0 of 231 tasks judged outright
replaceable"**. Building the read path disproved it.

`scripts/score_cohort.py` persists only the **target** occupation's task scores;
the other eleven cohort members contribute a single index each. So task-level
direction exists for three roles, not twelve, and the first implementation's bare
`COUNT(*) WHERE direction = 'substitute'` returned **"6 of 231"** — a sum across
five runs, three occupations and two different models, over a denominator that
includes nine roles never scored at task level. Three incompatible populations in
one ratio.

The figure now travels with its own scope, and the view model carries three fields
instead of one: `substitutable_count`, `substitutable_of`, `substitutable_roles`.
Scoped to the latest run per occupation under one classifier, the honest readings
are:

| Classifier | Reading |
|---|---|
| `gpt-6-astra` | 0 substitute, of 26 tasks, across 1 role examined in depth |
| `gpt-5.4-mini` | 3 substitute, of 68 tasks, across 3 roles examined in depth |

The hero figure becomes the portfolio claim the spec wanted only after §7.1
option B. Until then the page states the count, the denominator and the role
coverage together.

---

## 4. Chart inventory

Forms chosen by the data's job, before colour.

### 4.1 Exposure by role — horizontal bar, sequential

Job: compare magnitude across twelve long-named categories. Horizontal bars,
sorted descending, sequential single-hue ramp (more exposed is darker). Twelve
categories exceeds any categorical palette, which is the reason magnitude must
carry the colour rather than identity.

Direct value labels at the bar ends; no axis-number clutter. Rows for the nine
roles without a full run are marked and not clickable.

### 4.2 Adoption diffusion — line, two series

Job: trend over time, two distinct series. Two 2px lines, markers ≥8px, crosshair
tooltip, legend plus direct labels at the line ends. X axis labelled **"NAICS 52,
which pools banking and insurance with securities"** — the caveat belongs on the
axis, not in a footnote, because the chart is the thing that will be screenshotted.

### 4.3 Rank agreement — dumbbell, 12 rows

Job: before/after per item, which is what our rank versus the benchmark's rank is.
One row per occupation, two dots joined by a rule: our percentile and the AIOE
percentile within the same cohort.

This is the chart that makes the calibration argument visible instead of verbal.
Where the two dots sit far apart, the orderings disagree; the spread across all
twelve is the rank correlation the gate already computes. A single delta number
would hide exactly what this shows.

### 4.4 Per-task distribution — the existing spine, reused

Already built: one ink rule per task, scaled to net exposure, inside the task
table. No new form. On a drill-down page it needs no change.

### 4.5 Forms explicitly rejected

- **No dual-axis anything.** Exposure (0–1), adoption (%) and lag (years) are three
  scales. Three charts.
- **No gauge, dial or donut** for exposure. It is a meter at most, and the report
  already uses one.
- **No treemap or bubble** for roles. Area is read badly and headcount — the only
  sensible size variable — is not in the warehouse.
- **No sparkline on the exposure tiles.** There is no per-role time series; a
  sparkline would be drawing noise across unrelated runs.

---

## 5. The validated palette

Run against the data-viz validator rather than eyeballed. The project's structural
navy **failed** as a series colour (OKLCH L 0.255, outside the 0.43–0.77 band;
chroma 0.046, reads gray) — it is ink, not data. Lifted and re-checked:

| Slot | Light | Dark | Checks |
|---|---|---|---|
| Sequential ramp, 5 steps | `#8FB9D1` `#669BBB` `#427AA0` `#215980` `#0C2537` | — | monotone L, ΔL ≥ 0.06, 9° hue spread, light end 2.04:1 — **all pass** |
| Series 1 (ours / current use) | `#2E7DA8` | `#0E8CD6` | — |
| Series 2 (benchmark / expected use) | `#A87A1E` | `#BC8C1C` | CVD ΔE 19.1 protan, 19.7 tritan; normal 21.9 — **all pass** both modes |

`#CC0000` stays reserved for the masthead rule, section marks and the primary
button. It never encodes a value, which is already enforced by
`test_the_spine_is_not_drawn_in_the_brand_colour` and the same test extends to
every new mark.

---

## 6. Build sequence

Numbered to continue the existing workstreams (W1–W9 complete).

### W10 — Cohort read path
The gateway can load one run. It cannot load the cohort as a client-facing object.
Add a `CohortView` to the application tier: twelve rows of (title, SOC, index,
tasks, has_full_run), plus the page-level lag and the KPI counts.

*Acceptance:* a test asserts the view is built from `score.cohort_index` filtered
to one classifier and one rubric version, and that mixing classifiers is
impossible. A test asserts `has_full_run` is derived from
`score.role_verdict`, not assumed.

*Depends on:* nothing. *Blocks:* W11–W13.

**Status: complete.** `app.gateway.load_cohort` → `CohortView`, 21 tests in
`tests/test_cohort_view.py`. Two defects found and fixed during the build: the
unscoped substitution ratio (§3.1), and three of my own loop-based tests that
passed vacuously on an empty cohort. `CohortRowView` carries no lag field at all,
so a per-role lag column is unrepresentable rather than merely discouraged.

### W11 — Chart primitives, as SVG we emit
No plotting library. Three reasons, in order of weight: chart geometry is a
figure and must join the traced set, which a library computes outside that path;
`blocks.py` is forbidden arithmetic by test, so geometry must be computed in the
gateway and passed in pre-formatted; and the page is one composed document with a
size budget.

Primitives: `bar_row`, `line_series`, `dumbbell_row`, `axis`, `legend`. Each takes
pre-computed coordinates as strings.

*Acceptance:* `test_no_chart_primitive_performs_arithmetic` parses the module and
fails on any arithmetic operator, mirroring the existing rule. Every coordinate
appears in `view.figures`.

**Status: complete.** `app/geometry.py` computes, `app/charts.py` emits, 36 tests
in `tests/test_charts.py`. Primitives: `bar_rows`, `line_series`,
`dumbbell_rows`, `legend`, `axis_note`, `table_view`.

One correction to the acceptance criterion. "Every coordinate appears in
`view.figures`" was wrong, and the first implementation obeyed it literally:
pixel lengths like `246.2` went into the traced set, each a datum multiplied by
an arbitrary plot width, which no reader can read and which floods the traced set
with numbers nobody can check.

`ChartGeometry` now separates the two. **`figures`** are the values printed as
text, which must already be traceable; **`layout`** are the positions marks sit
at. The distinction from the task spine's widths is real rather than convenient:
a spine width is `70%`, the datum as a share and readable as one, while a pixel
length is the datum times a plot width. Verified end to end — the rendered text
of the exposure chart contains no number outside `CohortView.figures`.

Every rule claimed here was mutation-tested: smuggling a `2 * 2` into
`charts.py`, painting the ramp `#CC0000`, removing the axis clamp and restoring
the pixel-length classification each produce failures.

*Depends on:* W10.

### W12 — Portfolio page: KPI row + exposure ranking
The hero figure ("0 of 231 tasks judged outright replaceable"), the tile row from
§3, and chart 4.1. The nine non-drillable roles render marked.

*Acceptance:* the lag appears exactly once on the page, asserted by a test that
counts its occurrences. No tile shows an average across roles.

**Status: complete.** `blocks.portfolio_blocks`, a `chart` block kind rendered by
`document._chart`, chart CSS, and a two-entry view selector with Portfolio as the
default. 21 tests in `tests/test_portfolio.py`.

The lag criterion earned itself immediately: it failed on the first run because
`10.1` appeared twice, once in the span and again in a prose sentence restating
it. The page lost the sentence rather than the test losing the criterion — the
span already prints all three numbers with their labels, so the prose was the same
redundancy already cut from the role report's section 2.

Both criteria were mutation-tested: adding a per-role lag column to the ranking
table, and adding an "Average exposure" tile, each produce the failure the test
claims to produce.

Two consequences of making Portfolio the default, both of which surfaced as red
rather than as a surprise later. Six role-report tests failed because they were
asserting against whichever page loaded first; their fixture now drives the
selector to "Role report". And `verify_stack --layer ui` failed for the same
reason, so it now verifies **both** pages — a chart on the portfolio, eight
sections and two tables on the report — rather than relaxing its expected counts
until the served page passed.

*Depends on:* W10, W11.

### W13 — Diffusion curve and rank agreement
Charts 4.2 and 4.3.

*Acceptance:* the NAICS 52 qualifier is in the axis label, asserted. The dumbbell
renders twelve rows with both percentiles from the same cohort, and a test fails
if the two series come from different cohort keys.

**Status: complete.** `gateway.load_adoption`, `gateway.load_rank_agreement` and
`gateway.load_portfolio`, wired as two sections on the portfolio page. 24 tests in
`tests/test_dashboard_charts.py`. The page now carries three charts of three
different forms — bars, lines, dumbbell.

The cohort-key criterion is enforced by bounds rather than by inspection. A
percentile within a cohort of n is bounded by the midpoint convention
(`100·0.5/n` to `100·(n−0.5)/n`), so a series ranked in a different population
cannot respect this cohort's bounds. A companion test proves the check is not
satisfied trivially: both series must *reach* the cohort's floor and ceiling,
which a series ranked among 774 occupations would not. Mutation-tested by
re-ranking the benchmark in its full population.

Both percentiles come from `scoring.cohort` — the same `calibrate_within_cohort`
and `percentile_of_rank` the gate uses, asserted structurally. Ranking twice by
two methods would let this chart and the gate disagree about the same occupation,
and the chart exists to make the gate's argument visible.

**The page scan found five classes of gap and one real defect.** Period labels,
axis ticks, NAICS codes and the unsigned form of a negative correlation all
needed tracing (the number scanner reads `-0.2452` as the literal `0.2452`, so
tracing only the signed form leaves a real figure looking like a provenance
break). The defect: **`774` was typed into new chart copy** — the benchmark's
full occupation count, which has no source in this warehouse and which had
already been removed from `BENCHMARK_ON_FILE` earlier in the project for exactly
that reason. Removed again, and a test now rejects any figure-shaped literal in
chart prose.

The two charts degrade independently. A missing adoption series or an unrankable
benchmark removes that section and logs its own reason; the ranking survives, and
the ranking itself still raises because a portfolio view missing rows looks like a
portfolio view.

Two W12 tests broke correctly and were updated rather than relaxed: one asserted
exactly one chart, the other asserted the UI called `load_cohort`.

*Depends on:* W11.

### W14 — Interaction and accessibility
Crosshair plus tooltip on the line, per-mark tooltip on bars and dots, a table
view behind every chart, dark-mode steps from §5 under both the media query and
the theme attribute, texture fill available for forced-colors and print.

*Acceptance:* `AppTest` executes the page and finds the table view for each chart.
Legend present for both two-series charts. Reduced motion respected.

**Status: complete.** 25 tests in `tests/test_chart_interaction.py`.

**The crosshair is CSS alone**, because `st.html` does not execute JavaScript —
verified in Streamlit's own source rather than assumed. One invisible hit band
per period reveals a sibling rule and carries a readout naming *every* series at
that period, which is the thing a per-mark tooltip cannot do: hovering one dot
gives one value, and the question a reader has at a point on a trend is what both
lines were doing. 21 slots on the live page, no script, no inline handlers.

**Colour moved out of the markup into CSS tokens.** Three reasons: dark steps
need somewhere to override, a token defined once cannot drift across three
primitives, and the no-brand-red rule becomes checkable in one place. A test
asserts no mark carries an inline colour, and a second asserts every mark class
has a rule behind it — a class with no rule renders an invisible bar, which is
worse than a tint.

**Dark steps are selected, not flipped.** The light pair fails the dark band
(OKLCH L 0.48–0.67, chroma ≥ 0.1; blues lose chroma at mid lightness), so
`#0E8CD6` / `#BC8C1C` were re-stepped and re-validated against the dark surface.
Declared under both the media query (with the `:not([data-theme="light"])` guard)
and the theme attribute. The page itself stays pinned light by
`.streamlit/config.toml` — an institutional paper, by deliberate choice — so these
exist so the charts do not break if the surface changes, not because a toggle
ships today.

Print folds into the one existing `@media print` block rather than adding a
second: tables open so a printed page is not missing its numbers, and the hover
layer is dropped because a crosshair cannot work on paper. Forced colors keeps
identity through texture and outlines once author fills are stripped.

Three defects during the build, all mine. A division landed in `charts.py` and
the parse test caught it on the next run — the hit-band width moved to
`ChartGeometry.hit_band`, because the rule that the presentation tier computes
nothing does not admit exceptions. A slice deletion swallowed `dumbbell_rows`,
`legend`, `axis_note` and `table_view`, restored from the previous commit with
the colour change re-applied. And **a mutation run defeated my own dark-steps
test**: it checked the validated values appeared *somewhere* in the stylesheet,
so flipping one scope back to the light pair passed. It now checks inside each
override block and rejects a light hue there.

*Depends on:* W12, W13.

### W15 — Provenance extension
Every chart coordinate traced, the way the spine's bar widths already are. The
rendered-text traceability test extended to cover SVG text nodes, which the
current tag-stripping regex removes.

*Acceptance:* a companion test injects an untraceable coordinate and proves the
check catches it. Without that, the extension is decoration.

*Depends on:* W11–W13.

### W16 — Verification and documentation
A `--layer dashboard` arm in `verify_stack.py` that counts charts, series and
traced coordinates and **fails below the expected counts** rather than reporting
zero as a pass. README section. Palette recorded with its validator output.

*Depends on:* all of the above.

---

## 7. Decisions I need from you

### 7.1 Do we score the other nine roles?

The ranking chart shows twelve; three can be opened. Options:

| | Cost | Result |
|---|---|---|
| **A. Ship 12 ranked, 3 drillable** | nothing | Honest, and a client will click a row that does nothing |
| **B. Score the 9 fully first** | ~250 model calls, ~35 min on the full profile | Every row opens; the portfolio view is complete |
| **C. Show only the 3** | nothing | Defensible and abandons the plural question the dashboard exists to answer |

My recommendation is **B**, because the dashboard's whole premise is the plural
question, and option A ships a known dead end in the primary interaction.

### 7.2 Where does the dashboard sit?

A second page in the same Streamlit app, or a tab above the existing report? The
report is a document; a dashboard is a different reading mode. I lean toward two
entries in the sidebar — "Portfolio" and "Role report" — keeping each page
coherent rather than stacking a grid on top of a document.

### 7.3 Is the client internal or external?

If this page is ever shown outside the firm, the hero figure and the diffusion
chart are the two things that will be screenshotted out of context. That argues
for the standing stamp appearing on the dashboard too, not only on the report.

---

## 8. What this layer will not do

It will not forecast. It will not rank roles by headcount or cost, because neither
is in the warehouse and inventing a weighting would be the single easiest way to
produce a confident wrong number. It will not show a per-role timetable. It will
not average exposure across occupations.

And it will not make the nine cohort-only roles look like the three full runs. Nine
of twelve rows are one number each, and the page says so.
