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

- `reference/Second_Machine_Age_Notes_edited.pdf`
- `reference/machines__platforms__crowds_notes_refined.pdf`

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
(`reference/Technical Design Document (TDD).pdf`, Cold-Chain Logistics AI-Assistant):
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
- **Four separate credentials.** `USR_FDE_RO` (agent), `USR_FDE_LOAD`
  (ingestion), `USR_FDE_SCORE` (scoring), `USR_FDE_AUDIT` (audit adapter,
  INSERT-only on the log). The agent can request a score but cannot write one,
  and no orchestration node holds a write credential of any kind. The fourth
  was added at architecture review; see the review-closed section below.
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

Four decisions were open at design time and are **all now resolved** — see the
architecture-review section below and TDD Appendix A. Decision 1 (task
weighting) resolved to equal-weight primary plus an adjacent-SOC sensitivity
bound; decision 3 resolved to no curve fitting, which was the honest choice and
the less impressive one.

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

---

## Gap closure pass (2026-09-21)

Swept every open item accumulated across the session and closed what did not
need Administrator rights.

**Closed:**
- **Graphviz installed** (portable build to `~/AppData/Local/Programs/Graphviz`;
  winget hung and was abandoned after two attempts).
- **`Architecture_V2.png` regenerated** from the corrected `.dot`, 4538×2199,
  no Graphviz warning. Twelve edits: `splines=ortho` → `polyline` (ortho
  silently drops edge labels, which is what put "categorical task judgments" on
  the *lag* edge and inverted the diagram's central claim), ingestion relabelled
  append-only, `audit.run_source_binding` and the **Local Audit Adapter**
  holding `USR_FDE_AUDIT` added, all seven node→audit edges rerouted through
  the adapter, and the traceability statement now runs through the binding step.
  Verified visually, not just by exit code.
- **`tests/test_privileges.py`** — 25 assertions across all four principals.
  Currently skips with a precise reason per principal; becomes real the moment
  mixed-mode auth is enabled. Replaces the single inverted assertion that
  merely recorded the gap.
- **`scripts/enable_sql_auth.ps1`** — turnkey: registry, service restart,
  per-principal password generation into `.env`, login creation, verification.
- **Stale docs fixed:** "three separate credentials" → four; "Decision 1 blocks
  P1" → all four decisions resolved.
- **Reference material moved to `reference/`** with a README explaining what
  belongs there. Project root now holds only `CLAUDE.md`, `README.md`,
  `requirements.txt`, `pytest.ini`.
- **`verify_database.py` vs `test_guardrails.py`** — the overlap is deliberate,
  not duplication: the script checks *production*, the suite checks the rebuilt
  test database. A hand-patched production schema shows up only in the former.
  Documented in the script.

**Still open, each needing something only the user can do:**
1. **Mixed-mode auth** — needs elevation. Script is ready; it restarts the
   instance, dropping connections to the other 26 databases.
2. **Full-Text Search** — needs the SQL Server 2022 installation media; the
   local bootstrap has no cached feature payload. Exact command in the README.
3. **BLS v2 key** — free re-registration. Adapter already probes and falls back.
4. **Credential rotation** — six keys have been in a shared directory, and the
   repo is public.
5. **Stale `OPENAI_API_KEY` env var** — user is handling.

Deliberately *not* done unilaterally: the registry change and service restart.
I can make the registry write via `xp_instance_regwrite` as sysadmin, but doing
so without the restart would leave the instance silently switching auth mode on
its next reboot. Preparing the script and handing it over is the honest option.

---

## W4 complete — tool surface and run-source binding (2026-09-21)

369 tests pass, 29 skip with stated reasons. Branch `feat/p4-tool-surface`.

Six read tools over five views: `get_tasks`, `get_exposure_benchmarks`,
`get_adoption_curve`, `search_claims`, `get_industry_metric`,
`get_source_document`. Six tools, not twenty datasets — the view set is the
scope control.

Three properties enforced rather than assumed:
- **Scope** — `ALLOWED_VIEWS` whitelist checked before execution, plus an `ast`
  test that parses `evidence.py` and fails if any tool SQL names a base table.
- **Provenance** — a row without `Source_Doc_ID` raises `ProvenanceMissing`.
- **Consumption** — bound when a tool *returns* a row carrying the source.
  The operational definition is stated in the module: stricter is
  unobservable, looser binds the warehouse, returned-to-caller is the narrowest
  measurable boundary. Zero rows bind nothing.

`AuditAdapter` holds `USR_FDE_AUDIT` and is the only writer to
`AgentAuditLog`. No orchestration node holds a write credential; nodes call
`emit`. `tool_raw_output` stored unmodified.

`run_scoring.py` now reads through the tool surface, so binding and audit are
exercised now rather than first appearing in W5. Verified in the database:
4 bindings across 4 usage types, 6 audit entries with raw output preserved.

**Exposure index moved 0.555 → 0.541** — not drift. The earlier
`examin.*facilit` fix now correctly places "Assess companies as investments by
examining company facilities" in the manual cell (0.037). A language model does
not walk a factory floor.

Two real findings:
1. **`claude-opus-5` can spend its entire token budget on reasoning and return
   `text=None`.** Observed live at `max_tokens=16` with
   `reasoning_tokens == output_tokens`. `complete()` returned that silently
   while `structured()` already raised for the same cause; it now raises with
   the cause named. This would have surfaced in W5 as a mysteriously empty
   classification.
2. A structural test matched the module **docstring** rather than SQL, because
   the prose contained "FROM ". Now requires `SELECT` and `FROM`, plus an
   assertion that some SQL was actually found — otherwise the test passes
   vacuously.

`search_claims` falls back to `LIKE` without FULLTEXT and reports it in the
result, not just the log.

Next: W5, orchestration nodes. All dependencies are in place.

---

## Credential precedence fixed (2026-09-21)

The stale `OPENAI_API_KEY` turned out to be **Machine scope**, so removing it
needs Administrator rights I do not have. Rather than leave the project broken
in a normal shell, I fixed the precedence rule — which was the actual defect.

**New rule, most specific source wins:**
1. An env var **explicitly set for this process** (someone exported it; they
   meant it)
2. The project's **`.env`**
3. An **inherited** user- or machine-scope env var

Not plain environment-beats-file. A machine-scope variable is system-wide
configuration; a project's `.env` is narrower and more intentional, so the
project wins. `config.persisted_env_value()` reads the Windows registry
(unprivileged — only *writing* needs elevation) to tell an inherited variable
from a deliberately exported one. `config.key_sources()` reports the winner per
credential.

Verified: all six keys now resolve from `.env`, the live provider tests pass,
and **the full suite is green in a normal shell** — 391 passed, 29 skipped,
three consecutive runs. No more `unset OPENAI_API_KEY` workaround.

22 new tests in `tests/test_config.py` cover the whole ladder, the logging, and
the `.env` parser's tolerance for every format the file has been hand-edited
into.

The machine variable is now harmless but still misleading. Optional cleanup,
elevated: `[Environment]::SetEnvironmentVariable('OPENAI_API_KEY', $null, 'Machine')`.
Nothing depends on it.

---

## W5 complete — orchestration nodes (2026-09-21)

497 tests (466 without credentials), 29 skipped. Branch
`feat/p5-orchestration-nodes`.

Four model nodes plus deterministic retrieval, each a plain function over
`RunState` so it is testable alone. Graph assembly is W6.

**The comparison the plan demanded — same 26 tasks, baseline vs model:**

| | Baseline | Model |
|---|---|---|
| Exposure index | 0.541 | 0.384 |
| Direction resolved | 0/26 | **14/26** |
| …as substitute | 0 | **0** |
| Low confidence | 26/26 | **0** |
| Cited evidence | 0 | **14** |

**The model earns its cost**, on the field that matters: the baseline cannot
tell augmentation from substitution and says so on every task; the model
resolves it on 54% and cites evidence doing so. It returned **zero**
`substitute` judgments — independently landing on the augmentation reading the
survey prior supports. The lower index is a *consequence* (higher tacitness
than keyword matching, the direction Polanyi predicts), not proof of accuracy,
and the README says so rather than claiming 0.384 is "righter" than 0.541.

Cost: 28 calls, 30,047 tokens, 3.4 min.

**Independence demonstrated live:** `baseline lag identical: True`. Swapping
the entire classification layer left the lag interval byte-identical.

**The gate reasoned correctly on its own:** emitted `review_required` naming
*"an unidentifiable comparison, not a numeric disagreement"* — exactly the
distinction the three-state design exists for. No narrative produced, as
`review_required` should not yield a report.

Refusals built into the nodes, each with a test:
- Intent halts on an unpublished occupation and **verifies the model's SOC
  against the catalogue** rather than trusting the schema, which only
  constrains the type. A confident answer about a different role is the worst
  failure this system could have.
- Classifier drops invented citations and records them; a schema violation
  degrades one task, not the run; the fallback is *non-routine* so a failure
  cannot inflate exposure.
- Gate computes structural checks in Python **before** consulting the model, so
  a hard failure never depends on a model noticing it. It cannot upgrade a
  rejected calibration, and an unavailable gate rejects rather than waving the
  run through.
- Synthesis gets one retry with the offending figure named, then produces **no
  narrative at all**. A fluent report with one invented number is worse than no
  report.

`nodes/figure_guard.py` is the mechanism behind "no unsourced figures":
allow-set from verdict + scores + evidence, every number in the draft checked
against it. Calibrated both ways — catches invented percentages, years and
headcounts; does not fire on "three caveats", on 0.54 rounded from 0.541, or on
a share quoted as a percentage.

One honest observation: the classifier cited evidence on 14 of 26 tasks, not
all 26. Verified the evidence *does* reach the prompt (9 claims, correctly
formatted), so the model is choosing not to cite on some tasks. Worth a prompt
iteration in W6, not a defect.

Next: W6, LangGraph assembly. LangGraph is installed; the nodes are already
graph-shaped.

---

## W6 complete — graph assembly (2026-09-21)

511 tests pass, 29 skip with stated reasons; three consecutive full-suite runs plus a forced-order run, all clean. Branch `feat/p6-graph-assembly`.

LangGraph now owns control flow. The architecture's central claim is no longer
a paragraph in the TDD — it is the shape of the graph:

```
intent_scope -> evidence_retrieval -> { exposure_path | lag_path } ->
assemble_verdict -> review_gate -> synthesis
```

`build.edges()`, `reaches()` and `concurrent_write_conflicts()` read the
**compiled** graph, so the topology tests assert what was built rather than
what was drawn.

**Independence is now enforced at a fourth level.** Behavioural, interface and
`ast`-structural were already in place; the graph adds reachability (no path
from either scoring branch to the other, in either direction) and declared
field ownership (`NODE_WRITES`, with the intersection of the two branches'
write sets asserted empty).

**Termination is structural.** `route_after_gate` routes anything but a clean
pass to `END`, so an unreviewed figure has no path to a narrative. LangGraph
omits conditional edges targeting `END` from its drawable graph, so that branch
is asserted through the routing function, not the edge list — a test that
looked at the edges would have passed vacuously.

Five bugs found during the build, four of them real:

1. **Field-ownership write race.** A node returning a whole `RunState` is an
   update to *every* field, so the classifier wrote `lag=None` in the same
   superstep as the lag branch wrote the real interval. `NODE_WRITES` now
   declares what each node owns and the wrapper returns only those keys.
2. **Asymmetric fan-in fires the join twice.** Probed and confirmed: with a
   two-hop and a one-hop branch, LangGraph 0.3.34 runs the join once per
   incoming edge rather than waiting. `add_node(defer=True)` would fix it but
   is not in this version, so classification and scoring were merged into one
   `exposure_path` node. The classifier is still its own tested module; it is
   simply not its own graph node.
3. **Gate/calibration status precedence.** `close_run` derived the persisted
   status from calibration, so a `gate_rejected` run would have been stored as
   `passed` — the audit record would have contradicted the gate. `close_run`
   now takes `gate_outcome` and it wins.
4. **`AgentAuditLog.status` was `NVARCHAR(16)`** and truncated on the longer
   outcomes. Widened to 32 by idempotent ALTER.
5. My own two test expectations about the pass path were wrong, which is how
   finding (6) below surfaced.

**Test isolation bug in my own suite, worth recording.** Two guardrail tests
asserted an *absolute* `COUNT(*)` on `audit.AgentAuditLog`. The audit adapter
writes under autocommit — correctly, because an append-only log that a
rollback can erase is not append-only — so the graph fixtures' entries survive
into later tests. The suite passed in isolation and failed in order. Both now
assert a delta, or scope to their own marker. A suite that is green only in one
order is not green.

**The limitation is now a test.** `test_production_cannot_currently_reach_a_pass`
pins it: one scored occupation has no percentile of its own, so calibration
returns `review_required`, the gate cannot upgrade it, and the graph produces
no report. Scoring several occupations unblocks it; changing the gate would
only hide it. `NodeDeps.our_percentile` exists solely so the pass path stays
testable, and is `None` in production.

Next: W7, the customer-facing report and provenance appendix.

---

## W7 complete — report and provenance (2026-09-22)

565 tests pass, 29 skip with stated reasons (54 new in `tests/test_report.py`); three consecutive full-suite runs plus a forced-order run, all clean. Branch `feat/p7-report-provenance`.

Seven sections, rendered deterministically from persisted rows. No model
involved. Exposure and lag appear as separate findings and are never combined.

**Decision taken, and it changed the TDD's reading.** The TDD says
`review_required` yields "no automatic report". You asked for the report to
render that state instead, on long-term grounds, and that is right — but the
reconciliation matters more than the choice. The gate withholds *model prose*,
not rendered data, and "halts for human review" presupposes an artefact for the
human to review. So there are now two outputs: the **narrative** (model-written,
`pass` only, unchanged) and the **technical report** (deterministic, any run
reaching a verdict). The report leads with its own standing, so an uncalibrated
run says so in section 1 before any figure appears.

**Provenance is a precondition, not an audit.** `report/figures.py` is the only
way to put a number in the document, and it refuses a figure that cannot name a
source. This deliberately inverts `nodes/figure_guard.py`: there a *model*
writes the prose so numbers are checked afterwards; here the renderer is ours,
so an unprovenanced number is unrenderable rather than caught. The two failure
modes mean different things — a guard failure is a model fabricating, a
registry failure is a renderer bug.

**The traceability walk** (`report/provenance.py`) takes every figure through
`score.*` → `audit.run_source_binding` → `ref.source_document` → SHA-256, and
separates four break modes. Only three break it; an unverified mirror is a
qualification that blocks customer delivery without invalidating the document.
Against the real warehouse: **126 figures traced, 0 unregistered, 0 unbound,
0 unhashed, 1 unverified mirror** (Felten AIOE, flagged in section 1).

Two design points that keep the walk from being decorative:
- `unregistered` is checked against the **rendered text**, not the registry, so
  it catches a renderer bypassing the registry. Checking the registry against
  itself would pass vacuously.
- Code spans are skipped because they hold identifiers, and
  `test_no_code_span_is_purely_numeric` closes the hole that opens — a figure
  cannot be smuggled in by wrapping it in backticks.

**A latent defect, found by building the renderer.**
`score.calibration.our_percentile`, `benchmark_percentile` and `delta` were
`NOT NULL`, so `persist_verdict` substituted `0.0` for an absent value. Every
single-occupation run had therefore been persisting **"our percentile 0.00,
delta 0.00"** — a score at the bottom of the distribution in exact agreement
with a benchmark the same row records it as failing to match. It had sat there
since W2 because nothing rendered calibration until now. The columns now admit
NULL, the writer stores NULL, and the six affected development rows were
corrected; all six were provably coerced, since a real computation against a
benchmark of 86.82 cannot yield a delta of zero. Guarded at the real write path
by `test_persist_verdict_writes_null_not_zero_for_an_absent_percentile`.

Worth noting: that correction ran as the developer fallback. `db_fde_score`
holds `DENY UPDATE ON score.calibration`, so once mixed-mode auth is enabled
the same statement would be refused — the guardrail behaving exactly as
designed.

**Two bugs the walk caught that a reviewer would not have.**
1. *Truncation manufactured a figure.* The renderer registered the full quote
   and rendered a shortened one, so cutting "2025" mid-token left a bare "25"
   in the document that appeared in no source. What is registered is now
   exactly what is rendered, and `_shorten` falls back to a whitespace
   boundary.
2. *A benchmark cited without a binding.* The report wanted to print the
   benchmark percentile on a run that never bound an `exposure_benchmark`
   source. The figure is withheld and the absence stated — a number that cannot
   be traced to an artefact *this run consumed* is unsupported for this run
   even when it is correct in general.

The appendix also resolves claim evidence to verbatim quote plus page, and
states its own binding granularity: `run_source_binding` records the artefact,
not the individual quote, so the trace is source-level and says so.

**Visible now that the quotes are rendered:** some extracted claims are
low-value (a dedication line, a JEL-code block) because the PDF extraction
takes the first matching passages. Not a W7 defect — it predates this
workstream — but the appendix makes it customer-visible, so claim selection is
worth a pass before any external delivery.

Next: W8, the Streamlit presentation tier.

---

## Full-stack verification (2026-09-22)

Before starting W8 you asked for proof that every configured API actually
works. `scripts/verify_stack.py` is the repeatable answer: six credentials,
four government APIs, two model providers, the warehouse, the tool surface,
and the pipeline from graph run to traceability walk. **18 pass, 0 fail,
2 skip.**

| Layer | Result |
|---|---|
| Credentials | 2/2 — all six resolve from `.env`, precedence holds over the stale machine variable |
| Government APIs | 4/4 live, 1 skip — BLS, BEA, Census, FRED, through the project's own adapters |
| Model providers | 4/4 — `gpt-6-astra` strict `json_schema`, `claude-opus-5` forced tool use, vendors disjoint |
| Warehouse | 3/3, 1 skip — five views populated, six tools returning provenanced rows |
| Pipeline | 5/5 — 28 calls, 30,738 tokens, 164 figures traced, chain complete |

Two design choices in the script: it calls **the project's adapters rather than
raw HTTP**, because a probe that bypasses the code under test proves only that
the vendor is up; and **`SKIP` is never reported as `PASS`**, because an
unrunnable check rendered green is how a broken dependency hides.

**The real finding: the benchmark tool was lying about a miss.**
`VW_ROLE_TASKS` carries O*NET's 8-digit codes (`13-2051.00`); the AIOE
benchmark keys on the 6-digit SOC (`13-2051`). A caller passing the task-style
code got zero rows and the note read *"No published benchmark for this
occupation"* — false, and false in the direction that matters, because a
downstream reader would record the occupation as unbenchmarked and the run as
uncalibrated for a reason that is not the real one. `retrieval._benchmark_soc`
normalises correctly so no run was ever wrong, but any new caller — W8's
presentation tier being the obvious one — would have walked into it. The note
now names the code-system mismatch and says which code to query. Two tests:
the mismatch, and a genuine absence that must still read as an absence.

Same defect class as the null-vs-zero coercion in W7: a value that is wrong
about *why* it is empty. Worth watching for as a pattern.

**Run-to-run variation worth recording.** Exposure came out **0.380** against
W5's 0.384 on identical evidence — classifier non-determinism, ~1%. The lag was
**byte-identical** (5.0 / 10.07 / 30.0), which is the independence property
demonstrated again for free: swapping classifications moves exposure and cannot
move the lag.

The two skips are honest gaps, both needing you:
1. **BLS v2 key still rejected** — the adapter falls back to keyless v1 and
   logs it. Free re-registration.
2. **The "agent cannot read a base table" guardrail cannot be verified** —
   mixed-mode auth is off, so the check runs as the developer fallback rather
   than `USR_FDE_RO`. The script says so rather than passing. This is the
   single most valuable of the outstanding environment items: 29 privilege
   tests plus this guardrail all become real the moment it is enabled.

---

## W8 complete — presentation tier (2026-09-22)

612 tests pass, 29 skip with stated reasons (45 new in `tests/test_app.py`); three consecutive full-suite runs plus a forced-order run, all clean. Branch `feat/p8-presentation-tier`.

Eight sections in the browser at `127.0.0.1:8501`, rendering a run that already
happened. Standing first, provenance last, exposure and lag never combined.

**Four modules, one boundary.** `gateway.py` is the application-tier facade and
is the only one allowed to reach the warehouse. `view_model.py` is the boundary
object — plain strings and booleans, no handles. `blocks.py` says what to show,
as data. `streamlit_app.py` is a dispatcher: one block, one `st.*` call.

The tiers are logical and co-located in one process (TDD 4.1, "in-process
call"), so nothing *physically* stops a UI module opening a cursor. What stops
it is `test_the_ui_module_cannot_reach_the_database`, which parses the module
and fails on a database import or a SQL keyword. Same technique as W3's no-SDK
rule and W4's no-base-table rule.

**Renders no figure it did not receive**, enforced two ways:
- Every numeric literal on the page is walked back to the view model, which
  carries only literals the report's figure registry produced — and the
  registry already refused any figure without provenance. The chain now runs
  from a hashed artefact to a pixel.
- `test_no_block_performs_arithmetic` parses `blocks.py` and fails on any
  `-`, `*`, `/`, `//`, `**`, `%`. A presentation layer that could compute could
  produce a figure that is on no source, and the figure test would have nothing
  to catch it with.

Reuses `report.provenance._is_furniture` rather than defining a second rule for
what counts as document furniture. One definition, no drift.

**Proven to run, not just well-formed.** Structural tests cannot establish that
the blocks reach real `st.*` calls without raising, so six tests execute the
actual script through Streamlit's `AppTest` harness: **8 sections, 12 metrics,
3 tables, 2 warnings, 0 errors, no exception.** They skip with a stated reason
when nothing has been scored. Checking that the test was non-vacuous mattered —
it runs in 1.6s, which looked too fast until confirmed against a standalone run.

**The perimeter was probed, not assumed.** `run_ui.py` binds loopback;
verified live as reachable on `127.0.0.1:8501` and **connection refused on the
machine's LAN address**. Now a standing check in `verify_stack.py --layer ui`.
A `--host` override exists and warns loudly, because the app serves a
customer-facing analysis with no authentication in front of it.

**Environment problem found and fixed.** Streamlit 1.57 was installed but
**could not import at all** — it needs `starlette>=0.40` while `fastapi` pins
`<0.39`. Pinned to **1.49.1**, the last tornado-based release, which requires no
starlette, so the conflict disappears rather than moving to another package.
`langgraph` itself never depended on starlette; only `langgraph-api`, which this
project does not use. Its conservative `pillow<12` cap was *tested* rather than
obeyed: 1.49.1 runs fine on pillow 12.3.0, which matters because an unrelated
package of yours needs `>=12.1.1`. Pinned in `requirements.txt` with the
reasoning, so nobody upgrades back into the broken state.

Next: W8 was the last workstream in `docs/build_plan.md`. The build plan is
complete; what remains is the environment work only you can do, and a second
occupation to make calibration identifiable.

---

## W9 complete — cohort calibration (2026-09-22)

648 tests pass, 30 skip with stated reasons (36 new in `tests/test_cohort.py`). Branch `feat/p9-cohort-calibration`.

**A correction first.** I told you scoring one more occupation would make the
calibration gate functional. That was wrong. `percentile_within` already
refused distributions below ten points, so a second occupation would have
changed nothing — and there was a second, worse problem I had not seen:
Felten/Raj/Seamans rank Financial Analysts among **774 occupations**, so our
index ranked among a handful we scored is a percentile of a different
population. Comparing the two would have looked like calibration and measured
nothing.

**The fix: rank both series within the same cohort.** Score N occupations, rank
our index among those N, rank the benchmark among *those same N*. Both
percentiles then describe one reference set and the comparison is identified.

This is also the right comparison for two different estimands. AIOE is a
standardised index over work activities; ours is a task rubric with a tacitness
discount. Their *levels* were never commensurable, so a level comparison was
always noise. Whether the **orderings** agree is the meaningful question — a
rank question — so the cohort statistic is Spearman's rho and the
per-occupation delta is its local view.

**The cohort was already on disk.** Every SOC 13-2* occupation with both O*NET
tasks and an AIOE value: **12 occupations, 231 tasks**. Nothing was fetched —
the O*NET dump in `data/docs` covers all 923 occupations and was already
hashed. Only 13-2051 had ever been loaded. One detail code per 6-digit SOC,
because AIOE keys on 6 digits and loading both 13-2099.01 and .04 would put one
benchmark observation into the distribution twice.

**The defect the first cohort run exposed, and this is the important part.**
The baseline cohort produced **delta 0.0 → `pass`** and **rank correlation
−0.4476** simultaneously. The target sat at rank 7 of 12 in *both* orderings by
coincidence while the orderings ran roughly opposite. A gate reading only the
target's delta would have certified a rubric that anti-correlates with the
benchmark — the exact failure mode of single-point calibration, which is the
thing cohort calibration was supposed to fix.

The gate now requires **both** bars: delta within tolerance **and** rank
correlation ≥ `MIN_RANK_CORRELATION` (0.30, provisional and labelled so).
`CALIBRATION_POLICY_VERSION` moved to `provisional_v2_cohort` because the
criterion changed and a figure calibrated under the old rule is not comparable
to one under the new.

**The reference set is stored, not recomputed.** Deriving it costs one model
call per task across every member; an interactive run cannot pay that to answer
a question about one occupation. `score.cohort_index` holds it, keyed on
`(cohort, classifier, rubric_version)` — a cohort scored by two classifiers is
not one cohort, and the key makes the mixture unrepresentable rather than
merely discouraged.

**An invariant I broke and then fixed.** My first cut had the graph node open
its own connection to load the cohort. `NodeDeps` states in its own docstring
that a node holds no credential and reaches data only through `tools`, and that
is what the tier split rests on. Moved to `graph/runner.load_cohort_reference`,
which is the application tier and legitimately holds the credential; the node
ranks but never loads. A missing reference set degrades to "not identifiable",
never to a percentile over whatever rows happen to be present.

**Limits, reported in the output rather than buried.** Granularity is 100/N —
8.33 points at N=12 against a ±15 tolerance, so one position change moves the
delta by more than half the tolerance. And a percentile within a chosen cohort
is a statement about that cohort: this one is the finance family, which is the
right frame for the customer question and the wrong frame for any claim about
the whole economy. Both are appended to the run's `unresolved` list and reach
the report and the UI.
