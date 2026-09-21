# CLAUDE.md — Project Charter

## Why this project exists

This is one project in a **portfolio series** aimed at landing a
**Forward Deployed Engineer** role at a financial firm — Bloomberg, DE Shaw, or
similar. Every decision in this repo should be legible as evidence of FDE
skill: talking to a customer, scoping a real problem, and shipping a prototype
that a non-engineer stakeholder can use and reason about.

## Domain grounding

The domain knowledge comes from the user's own reading notes on two books by
**Erik Brynjolfsson and Andrew McAfee**:

- `Second_Machine_Age_Notes_edited.pdf`
- `machines__platforms__crowds_notes_refined.pdf`

These notes encapsulate the history of technological disruption to the
**economy, the labor force, and innovation** — general purpose technologies,
complementary innovation, bounty vs. spread, skill- and capital-biased
technical change, platforms, and the mind/machine rebalancing.

Treat the notes as the **primary source of the analytical frame**. The
prototype's job is to apply that frame to the present wave: **the diffusion of
LLMs and agents**.

## Target customer

Business and finance firms — asset managers, banks, research desks, strategy
and corp-dev groups — who want **deep, defensible understanding** of how LLM
and agent diffusion will disrupt the economy, work, and innovation, and what
that implies for their capital and hiring decisions.

They are not buying a chatbot. They are buying **judgment they can act on**,
with the reasoning exposed.

## How we work

- **Iterative and customer-facing.** Each cycle: sharpen the customer problem,
  build the thinnest thing that answers it, put it in front of the customer,
  learn, repeat.
- **Prototype, then productionize.** Bias to a working end-to-end path over a
  polished fragment.
- **Deliverable-oriented.** Ask on every change: what does the customer see,
  and does it change a decision they're making?
- **Show the reasoning.** Analogies to prior GPT waves must be traceable to the
  notes, not asserted. No hype, no fabricated certainty; state uncertainty and
  degrade gracefully when evidence is thin.

## Standing objective

Build prototypes that turn Brynjolfsson–McAfee's disruption framework into
**decision-grade analysis of LLM/agent diffusion** for business and finance
customers — delivered iteratively, and strong enough to stand as portfolio
evidence of Forward Deployed Engineering work.

## Scope note

The CrewAI research-and-writing charter that previously sat at
`~/Downloads/CLAUDE.md` has been moved to
`~/Downloads/crewai_lwia_research_writer/CLAUDE.md` so it no longer bleeds into
this project. `code_test/` now has exactly one governing charter: this file.

---

## Project #1 — Task Exposure & Adoption Lag

**Customer question:** *Which of our cost lines are exposed to agent
substitution, and on what timetable?*

**Input:** one finance job family (scope deliberately narrow for project #1).

**Scoped for project #1:**
- **Job family:** sell-side equity research associate. Chosen because it mixes
  clearly exposed tasks (data pulls, model updates, note drafting) with clearly
  tacit ones (management access, thesis judgment), so the score has to
  discriminate rather than saturate.
- **Task source:** O*NET task statements — public, structured, citable, and
  standard in the labor-economics literature the frame comes from. Provenance
  has to survive a skeptical customer.

**Method, grounded in the notes:**
1. Decompose the role into discrete tasks.
2. Score each task on the Acemoglu–Autor routine/non-routine × cognitive/manual
   matrix, plus a **tacitness penalty** from Polanyi's paradox — Autor's bound:
   substitution "is bounded because there are many tasks that people understand
   tacitly and accomplish effortlessly but for which neither computer
   programmers nor anyone else can enunciate the explicit rules."
3. Attach an **adoption-lag estimate** anchored to the electrification
   precedent (Devine; Atkeson–Kehoe; David–Wright; Brynjolfsson 1993). The
   payoff is not in the machine — it is in the reorganisation the machine
   permits, and that reorganisation takes years.
4. Emit exposure **and** lag as separate quantities. Exposure ≠ timing.

**Guardrails carried from the notes:**
- Exposure must not collapse into "replaced." Snijders: aided experts land
  *between* the model and the unaided expert — and the model alone still beats
  both. Report the augmentation case explicitly.
- Direction is chosen, not given (Acemoglu & Johnson). The same capability can
  automate a task or augment the worker doing it; say which the score assumes.
- Where evidence is thin, degrade gracefully and say so. No fabricated
  certainty, no hype.

**Output the customer sees:** a per-task table (exposure, tacitness, lag) rolled
up to a role-level verdict, with the reasoning traceable to the frame.

**Decision it changes:** next-cycle hiring plan and automation budget.

**Deferred to later projects:** bit-intensity / platform-vs-pipeline scoring
(project #2, the tail-index paper in prototype form); productivity J-curve
monitoring; distributional tier analysis (reuses this project's task engine).

---

## Data layer (built 2026-09-19)

Four government APIs, 20 datasets, all landed as CSV under `data/raw/` with a
self-describing manifest. See `README.md` for layout and `notes/data_exploration.md`
for findings. Key facts that constrain later work:

- **BLS key is invalid** against v2; the adapter falls back to keyless v1 and
  logs it. Re-register to restore the wider query window.
- **Census ABS technology modules are 2-digit NAICS only** — no securities (523)
  breakout for adoption. BEA *does* break out 523 for labour share and value
  added. Adoption and cost line therefore sit at different granularities, and
  the score must say so rather than paper over it.
- **Adoption data is pre-LLM** (2018, 2020 vintages). It bounds the prior on
  how fast a capability diffuses through finance; it is not evidence about agents.
- **BTOS** (current biweekly AI-use rates) is flat-file only, not on the API.
  Highest-value next extension.

Findings that should shape the scoring rubric:

1. Finance ranked 3rd of 21 sectors on AI use in 2018 at 4.5% of firms, against
   48.8% on cloud and 55.2% on specialised software — a 44-point
   substrate-to-capability gap. The reorganisation lags the machine, exactly as
   the electrification precedent says.
2. NLP specifically was at 1.1% of finance firms in 2020 — the pre-LLM baseline
   for the capability that touches analyst drafting and extraction work.
3. Among firms that adopted AI, the dominant reported effect in finance was
   **more skilled workers (47.2% up, 1.6% down), not fewer workers**
   (12.5% up, 8.4% down). The augmentation reading has the stronger prior, and
   an exposure score that outputs "replaced" must clear that bar.
4. Finance churn has *fallen*: establishment entry and exit both ran ~11-12%
   in the 1990s and ~8.5-9% in the 2010s-2020s. Whether concentration under
   this GPT ends in displacement is open, and recent data leans against it.

---

## Document layer (built 2026-09-19)

Nine documents, four formats, normalised into one typed `Corpus`. The agent's
tools will expose `Task` / `ExposureEstimate` / `AdoptionObservation` /
`ExtractedClaim` — never a file format. See `notes/corpus_exploration.md`.

What it changes about the plan:

1. **BTOS closes the adoption gap.** Finance firms using AI went from 29.9%
   (June 2025) to 36.5% (April 2026), with 43.8% expecting to use it within six
   months. Against ABS 2018's 4.5% and 2020's 1.1% NLP, we now have the whole
   diffusion curve rather than only its pre-LLM start.
2. **We have an external calibration target.** Felten/Raj/Seamans put Financial
   Analysts at the 87th percentile of 774 occupations for language-modelling
   exposure. Our rubric has to be reconciled with that number, not invented
   beside it.
3. **Eloundou et al. explicitly decline to forecast timing** (p.1, verbatim in
   the corpus). That is direct support for keeping exposure and lag as two
   separate outputs, which is how project #1 was scoped.
4. **O*NET has no ratings for 13-2051** — analyst-written task list, no
   incumbent survey. Open decision: weight all 26 tasks equally, borrow ratings
   from an adjacent occupation (13-2099.01 Financial Quantitative Analysts is
   closest and is rated), or move the target role. Must be decided explicitly,
   not absorbed silently.

Provenance rules now in force: every document carries a SHA-256; every
prose-derived claim carries a verbatim quote plus page number; mirrored sources
are flagged and must be spot-checked before customer-facing use.

---

## Architecture (designed 2026-09-19)

TDD at `docs/technical_design.md`, structured to match the reference TDD
(`Technical Design Document (TDD).pdf`, Cold-Chain Logistics AI-Assistant):
HLD/LLD split, three-tier decoupling, security at the physical database layer,
append-only audit, deployment topology + network perimeter.

Load-bearing decisions:
- **Three tiers.** Stateless Streamlit (localhost:8501) / LangGraph state
  machine / SQL Server `FDE_TaskExposure` on 127.0.0.1:1433. No cloud.
- **The agent never touches a base table.** It reads five flat views
  (`VW_ROLE_TASKS`, `VW_EXPOSURE_BENCHMARK`, `VW_ADOPTION_CURVE`,
  `VW_CLAIM_EVIDENCE`, `VW_INDUSTRY_METRIC`) through `USR_FDE_RO`, which is
  denied every base table and all DDL. The view set is also the scope control:
  only project #1's datasets are published.
- **Three separate credentials.** `USR_FDE_RO` (agent), `USR_FDE_LOAD`
  (ingestion), `USR_FDE_SCORE` (scoring). The agent can request a score but
  cannot write one.
- **Agents judge categories; Python computes numbers.** Classifier decides
  routine/non-routine and tacitness; the deterministic service does the
  arithmetic. A model change cannot move a customer-facing quantity.
- **Not an open ReAct loop.** Fixed LangGraph node set, and the scoring node is
  not a model call.
- **`AgentAuditLog` is append-only** via DENY plus INSTEAD OF trigger, and
  stores `Tool_Raw_Output` unmodified so a disputed figure is attributable to
  either the evidence or the reasoning over it.
- **Guardrails enforced as constraints:** FK to `ref.source_document` makes an
  unprovenanced fact unrepresentable; `CHECK (LEN(caveats) > 0)` makes a
  caveat-free verdict unpersistable.
- **Exposure and lag on independent paths.** The lag never reads the exposure
  score.
- **P2 (deterministic scoring) ships before P3 (agents)** so the agents'
  contribution is measurable rather than assumed.

Four open decisions, all recorded in TDD §5.1. Decision 1 (task weighting for
13-2051) blocks P1. Decision 3 (whether to fit a logistic curve to a
sub-two-year adoption window, or decline and report a range) is the one where
the honest choice is the less impressive one.

---

## Architecture review closed (2026-09-19)

External architect reviewed; ten amendments applied to `docs/technical_design.md`.
Status is now **ready for P1**. No core design commitment was rejected.

The three changes that mattered:

1. **Append-only, content-addressed persistence** (TDD §B.0). `MERGE`
   idempotency and reproducibility are not the same requirement — a Census
   revision overwriting a row leaves a past run's `score.*` intact while the
   evidence beneath it silently changes. Facts are now append-only by source
   version; idempotency keys on source hash + natural key. This was a genuine
   defect in the original design.
2. **`audit.run_source_binding`** — binds a run to the exact source versions it
   *consumed*, not merely what was available. Deliberately no `source_version`
   column: under append-only, `source_doc_id` **is** the version identity and
   SHA-256 proves the content.
3. **`USR_FDE_AUDIT`**, held by a local audit adapter. Resolves a contradiction
   the original left open — every node must emit audit records, but
   `USR_FDE_RO` cannot write. No orchestration node now holds any write
   credential. `USR_FDE_LOAD` also lost `UPDATE`.

Our own catch during review: four of five views did not expose `Source_Doc_ID`,
which would have made the binding table unpopulatable. All five now do.

Decisions resolved:
- **Task weighting (13-2051):** equal-weight primary + adjacent-SOC (13-2099.01)
  sensitivity reported separately. Borrowed weights are endogenous to the
  question — importing a quantitative occupation's importance structure would
  move the result in the direction we are trying to measure.
- **Calibration:** three-state gate (`pass` / `review_required` /
  `gate_rejected`), ±15 points as `provisional_v1`. Calibration disagreement is
  not calibration failure.
- **Lag model:** no logistic fit. Observed trajectory + historical range +
  p10/p50/p90. The honest option, and the less impressive one.
- **Mirrors:** permitted internally with the flag surfaced; block the gate on
  customer-deliverable runs via `score.run.is_customer_deliverable`.

Open items carried forward: Graphviz binary is not installed locally (diagram
regeneration blocked); `Diagrams/Architecture_V1.png` has a mislabelled edge
(`splines=ortho` drops edge labels — switch to `polyline`) and predates the
append-only and `USR_FDE_AUDIT` changes. The `.dot` source is now in `Diagrams/`.

---

## P1 complete — database built (2026-09-19)

`FDE_TaskExposure` on `LAPTOP-FO95TROJ`. 15 tables, 5 views, 4 roles, 30 CHECK
constraints, 14 foreign keys, 1 temporal table, 1 append-only trigger.
46 DDL batches, idempotent, re-run verified twice with no duplication.

**17/17 guardrails verified adversarially** (`scripts/verify_database.py`) — the
script tries to violate each structural claim in the TDD and asserts refusal.
A guardrail that cannot be demonstrated failing is one nobody should trust.

Design choice that paid off: all permissions sit on **roles**, not logins, so
the security model is complete and testable even though the SQL logins cannot
yet be created.

Two bugs found and fixed during the build, both in my own tooling rather than
the schema:
- `setup_database.py` guessed at batch content by keyword and **silently
  skipped two MERGE batches while reporting success**. Seed data was empty and
  the run looked clean. Now skips only when nothing but comments remains.
- `verify_database.py` used one `execute()` for multi-statement batches, so
  pyodbc buried errors from every statement after the first — six guardrails
  falsely appeared to fail. Statements now run individually with result sets
  drained.

Still blocked on environment, both needing your go-ahead:
1. **Mixed-mode auth disabled** — `sql/06_logins_and_users.sql` cannot run.
   Needs a registry change plus a service restart affecting 26 other databases.
   Passwords in that script are placeholders and must come from env vars.
2. **Full-Text not installed** — `sql/07_fulltext.sql` skips itself cleanly.
   Needed for P3, not P1/P2.

Next: P2, the deterministic scoring service. It needs neither prerequisite.

---

## W1 complete — warehouse loader (2026-09-20)

17,004 facts loaded; 104 tests pass. Branch `feat/p1-warehouse-loader`.

| Table | Rows |
|---|---|
| `ref.source_document` | 29 |
| `core.task` | 26 |
| `core.exposure_estimate` | 774 |
| `core.adoption_observation` | 126 |
| `core.extracted_claim` | 21 |
| `core.industry_metric` | 16,057 |

**Append-only proven, not asserted.** A revised artefact becomes a new
`source_doc_id` with new rows; the prior rows survive verbatim and stay
resolvable. Re-running the loader against the real warehouse inserted 0 rows
and skipped 17,004 — idempotency on source hash + natural key holds in
production, not just in fixtures.

Design notes worth keeping:
- `registry._upsert_document` keys idempotency on **SHA-256, not doc_id**, so
  identical bytes under two names are one artefact and changed bytes under one
  name are two versions. Content addressing, as the architect argued.
- `_demote_superseded` demotes rather than deletes, so `VW_*` shows the latest
  version while history stays queryable for a past run.
- `weight_source` is written as `equal` on every task, making the aggregation
  convention explicit in the data rather than implicit in the code.

**What the tests revealed:** seven of ten quality assertions are also enforced
by a CHECK or FK, so the bad row cannot be inserted at all — for those the
constraint is the real guarantee and the assertion is defence in depth. Three
carry weight on their own: run-on quote detection, duplicate current versions,
and views exposing `Source_Doc_ID`. Stated in the README rather than left as an
implied "10 checks all passing".

**Honest gap:** mixed-mode auth is still off, so the loader runs as the
developer rather than `USR_FDE_LOAD`. `session.py` warns on every run and
`test_integration.py` asserts the isolation is *not* in force. It inverts when
mixed mode is enabled.

Next: W2, the deterministic scoring service. The independence test — asserting
the lag path cannot read the exposure result — gets written before the lag
model, not after.

---

## W2 complete — deterministic scoring service (2026-09-21)

234 tests pass. Branch `feat/p2-scoring-service`. No agent involved, by design.

**Control run, SOC 13-2051.00, 26 tasks:**
- Exposure index **0.555** (equal weighting); sensitivity bound 0.518–0.594
- Lag **p10 5.0 / p50 10.1 / p90 30.0** years, window 0.88 years, no curve fitted
- Calibration `review_required`; 100% unclear direction (baseline cannot tell)

The rubric discriminates: "Create client presentations" 0.900 against "Develop
and maintain client relationships" 0.405 and "Confer with clients to
restructure debt" 0.247. That spread is why this occupation was chosen.

**The independence test was written first and failed for the right reason.**
It enforces separation three ways — behavioural, interface, and structurally by
parsing `lag.py` with `ast`. The structural check survives refactoring: adding
the coupling requires deleting the test.

Three refusals now built in rather than documented:
1. `lag.py` holds the interval >= 15 years wide below a 2-year observation
   window, and widens even when handed a narrow prior.
2. Calibration returns `review_required` on a single-occupation run, because a
   percentile is a rank and one score has no rank. **This is a real finding:
   the calibration gate cannot function until several occupations are scored.**
3. The adjacent-SOC sensitivity is a *bound*, not a point. No task-level
   mapping exists between the occupations, so both extremal assignments are
   computed and the result holds under any mapping.

Design notes:
- `TaskClassification` has no numeric field. If a score could be supplied
  there, a model could set it.
- `TaskScore` validates `adjusted == raw * (1 - tacitness)`, so a hand-built
  score cannot lie about its own arithmetic.
- `baseline.py` is the control, not the product — every classification low
  confidence, direction always unclear. W5 must beat 0.555 meaningfully or the
  model is adding cost rather than judgment.

Two bugs found by the tests, both real:
- `lag.py` rounded p10 to nearest, which narrowed the interval past a value it
  was meant to contain. Now rounds directionally (floor the lower bound, ceil
  the upper) so rounding can only widen.
- `baseline.py` used `examine.*facilit`, which never matches "examin**ing**
  company facilities" — the one task that most needs the manual cell.

Warehouse now also holds 13-2099.01 (21 tasks with real O*NET ratings) so the
sensitivity bound has weights. `core.task` is 47 rows; task counts are asserted
per occupation rather than per table.

Next: W3, provider adapters. Both providers verified live; config already
points the Review Gate at Anthropic and the classifier at gpt-6-astra.

---

## W3 complete — provider adapters (2026-09-21)

310 tests (304 without credentials). Branch `feat/p3-provider-adapters`.

One interface, two genuinely different mechanisms, both established by probing
the live API rather than from documentation:
- **OpenAI** `/v1/responses` with strict `json_schema`. Function tools do not
  work on `/v1/chat/completions` for `gpt-6-astra`, and `reasoning_effort:
  'none'` is rejected for this model, so there is no workaround there.
- **Anthropic** has no `json_schema` response format. Structure comes from a
  single forced tool call whose `input_schema` is the contract; `stop_reason`
  returns `tool_use` and the tool input is the answer.

Neither adapter falls back to parsing prose. `SchemaViolation` carries the
offending payload so a bad response is debuggable without re-running the call.

A test parses every module outside `src/providers/` and fails if `openai` or
`anthropic` is imported — the charter's no-SDK-leakage rule, enforced.

Stage→vendor mapping lives in `providers/registry.py`, with a test asserting
the Review Gate is a different vendor from the Task Classifier. That is the
cross-provider independence property, not a stylistic choice.

**Cost accounting withholds rather than guesses.** Tokens are always recorded;
cost only when `PRICE_<MODEL>_INPUT`/`_OUTPUT` is configured. `gpt-6-astra`
postdates my reference material so its price is unknown here, and the ledger
reports `cost_status: unpriced_models: gpt-6-astra` instead of a total missing
half the calls.

Two real findings:
1. **`sleep` was bound as a default argument** (`sleep: Callable = time.sleep`),
   captured at import. Monkeypatching had no effect, so the retry tests were
   sitting through real backoff — the file ran in ~14s while appearing to
   control timing. Now resolved at call time; the file runs in 0.15s.
2. **A stale `OPENAI_API_KEY` environment variable on this machine shadows
   `.env`** and is invalid, surfacing as an opaque 401. `config.load_keys` now
   logs `status=env_shadows_dotenv` naming both suffixes when they differ.
   **Needs user action: unset or update the system-level variable.** The `.env`
   key itself is valid (verified HTTP 200).

Next: W4, view-backed tools and run-source binding. Blocked only on mixed-mode
auth for the privilege tests, which the plan already tracks as expected-skip.
