# Architecture Review Brief — for the reviewing software architect

**Attachments**
1. `docs/technical_design.md` — the TDD under review (651 lines)
2. `reference/Technical Design Document (TDD).pdf` — the reference TDD whose structure ours deliberately mirrors
3. `README.md` — what is built, how to run it, credential status, data limitations

---

## 1. What you are reviewing

A **Task Exposure & Adoption Lag Assistant**. One customer question:

> *Which of our cost lines are exposed to agent substitution, and on what timetable?*

The customer is a business or finance firm — the target profile is a research
desk, asset manager or strategy group — that needs a defensible view of how LLM
and agent diffusion will hit its own cost base. The first deliverable scopes to
**SOC 13-2051 (Financial and Investment Analysts)** in **NAICS 523 (securities,
commodity contracts and investments)**, US national.

The analytical frame comes from Brynjolfsson & McAfee (*The Second Machine Age*,
*Machine, Platform, Crowd*): a general purpose technology's payoff arrives not
with the machine but with the organisational reorganisation the machine permits,
and that reorganisation historically lagged by a generation. Two consequences
are load-bearing in the architecture:

- **Exposure and timing are separate quantities**, computed on paths that never
  read each other's output. The market routinely conflates them. The most-cited
  LLM exposure study (Eloundou et al.) explicitly declines to forecast adoption
  timing, and we hold ourselves to the same line.
- **Substitution is not the default reading.** Survey evidence in our own data
  shows the dominant reported effect of AI adoption in finance was *more skilled
  workers*, not fewer workers. An exposure score that outputs "replaced" has to
  clear that bar.

This is a prototype intended for delivery and for portfolio use, not a research
notebook. Design for defensibility under hostile questioning.

## 2. Environment constraints (non-negotiable)

- **Single local Windows 11 workstation.** No cloud infrastructure.
- **SQL Server Developer Edition**, local instance, database `FDE_TaskExposure`.
  The reference TDD deploys to AWS; we deliberately do not. Target customers run
  SQL Server/T-SQL estates, so this is closer to the real delivery environment.
- Python 3.11. Streamlit presentation tier. LangGraph orchestration.
- Anthropic for orchestration/gating, OpenAI for classification and narration;
  model IDs configurable by environment variable.

## 3. What is already built vs specified

**Built and working** (acquisition and normalisation, TDD §1.1 bottom tier):
- 20 datasets from four government APIs — BEA, BLS, Census, FRED — with a
  self-describing manifest recording each dataset's analytical purpose.
- 9 documents across four formats — O\*NET bulk TSV, two XLSX exposure
  appendices, Census BTOS wide XLSX, two academic PDFs — each with a SHA-256
  digest and a provenance note.
- All of it normalised into typed Pydantic contracts (`Task`,
  `ExposureEstimate`, `AdoptionObservation`, `ExtractedClaim`) so downstream
  code never sees a file format.

**Specified, not built** — everything else. Warehouse, view layer, RBAC, audit,
deterministic scoring service, orchestration, presentation tier.

## 4. Design commitments we want you to pressure-test

These are the choices we would defend; tell us where we are wrong.

1. **The agent never touches a base table.** It reads five flat views
   (`VW_ROLE_TASKS`, `VW_EXPOSURE_BENCHMARK`, `VW_ADOPTION_CURVE`,
   `VW_CLAIM_EVIDENCE`, `VW_INDUSTRY_METRIC`) through `USR_FDE_RO`, which is
   denied every base table and all DDL. The view set doubles as scope control:
   of 20 landed datasets only this use case's are published.
2. **Three credentials with disjoint grants** — `USR_FDE_RO` (agent),
   `USR_FDE_LOAD` (ingestion), `USR_FDE_SCORE` (scoring). The agent can request
   a score but cannot write one. The boundary is the credential, not the prompt.
3. **Agents judge categories; Python computes numbers.** The classifier emits
   routine/non-routine, cognitive/manual and tacitness flags; a deterministic,
   version-pinned service does all arithmetic. A model change must not be able
   to move a customer-facing quantity.
4. **Fixed LangGraph node set, not an open ReAct loop.** This is our one
   deliberate divergence from the reference TDD, which uses a ReAct agent as
   "the brain". Our output is a number a customer will budget against, so the
   path has to be reproducible.
5. **Guardrails as database constraints.** FK to `ref.source_document` on every
   `core` table makes an unprovenanced fact unrepresentable;
   `CHECK (LEN(caveats) > 0)` on `score.role_verdict` makes a caveat-free
   verdict unpersistable.
6. **Append-only audit** (`audit.AgentAuditLog`) via `DENY UPDATE, DELETE` plus
   an `INSTEAD OF` trigger, storing `tool_raw_output` unmodified so a disputed
   figure is attributable to either the evidence or the reasoning over it.
7. **P2 before P3** — the deterministic scoring service ships and is tested
   before any agent is wired in, so the agents' contribution is measurable.

## 5. Specific review questions

1. **Over-engineering check.** Is three SQL Server principals justified on a
   single-workstation deployment, or is it ceremony that will not survive
   contact with a real client environment?
2. **Evidence retrieval.** We propose SQL Server `FULLTEXT` over
   `core.extracted_claim.quote` rather than a vector store. Right call at this
   corpus size (~21 claims, low hundreds expected)? At what size does it break?
3. **Schema for re-runs.** `score.task_score` is keyed `(run_id, task_id)`. Is
   that adequate for comparing rubric versions across runs, or do we need
   explicit rubric-version dimensioning?
4. **Load strategy.** We specify idempotent `MERGE` on natural keys. Should this
   instead be append-only with effective dating, given that full reproducibility
   of a past run is a stated requirement (N1)?
5. **Extensibility.** Three sibling projects are planned on the same warehouse —
   a firm-size/tail-index study, a productivity J-curve monitor, and a
   distributional tier analysis. Their data is already landed. Does the fixed
   node set and per-use-case view layer scale to those, or will it force a
   rewrite?
6. **Portability.** What in this design would block lifting it from local SQL
   Server into a client's environment later — Azure SQL, or an on-prem estate we
   do not control?
7. **The coarseness question.** Does putting all arithmetic outside the model
   risk the classifier's categories being too coarse to carry the signal? Where
   would you draw the model/deterministic line differently?

## 6. Known hard constraints — please do not "solve" these

They are properties of the published data, not defects, and the architecture's
job is to state them honestly rather than paper over them:

- **Granularity mismatch.** Adoption data is sector-level (NAICS 52, pooling
  banking and insurance with securities); the cost line is NAICS 523. Census
  publishes no securities breakout for technology adoption. BEA *does* break out
  523 for labour share and value added.
- **No O\*NET ratings for 13-2051.** Its task list is analyst-written rather
  than survey-based, so there is no importance rating and no Core/Supplemental
  split. Adjacent occupations have ratings.
- **Pre-LLM adoption vintages.** The Annual Business Survey technology modules
  are 2018 and 2020. BTOS (2023–2026, biweekly) covers the LLM period and closes
  the gap, but the historical baseline is pre-LLM by construction.
- **BLS v2 key currently invalid**, so that adapter falls back to keyless v1,
  narrowing the query window. Logged as a WARNING on every run; re-registration
  pending.

## 7. Open decisions — your recommendation wanted

Recorded in TDD Appendix A §5.1. Decision 1 blocks implementation.

| # | Decision | Options |
|---|---|---|
| 1 | **Task weighting for 13-2051** *(blocking P1)* | (a) weight all 26 tasks equally — but that asserts "maintain client relationships" matters as much as "create client presentations"; (b) borrow ratings from 13-2099.01 Financial Quantitative Analysts and disclose the mapping; (c) change target occupation |
| 2 | **Calibration tolerance** | How far may our exposure percentile sit from the published benchmark (87th of 774 for 13-2051) before the Review Gate rejects a run? Too tight reproduces the benchmark; too loose makes the gate decorative. Proposed ±15 points — this is a guess |
| 3 | **Lag model form** | Observed adoption window is under two years (finance AI use 29.9% → 36.5%, Jun 2025 → Apr 2026) — arguably too short to identify a saturation level. (a) logistic fit with wide intervals; (b) report observed trajectory plus a range from historical GPT precedent and decline to fit. (b) is more honest and less impressive |
| 4 | **Mirror verification** | Two exposure-benchmark files came from a third-party reproducibility repository, not the publisher. Verify before internal use, or only before customer delivery? |

---

## 8. Deliverables requested

### 8.1 Written review

Against §5 and §7 above. Flag anything in §4 you would reject outright. We would
rather hear that a commitment is wrong now than discover it in P3.

### 8.2 Architecture diagram — PNG

Please return **a PNG**, plus **the editable source** (draw.io `.drawio`,
Excalidraw `.excalidraw`, Mermaid `.mmd`, or Graphviz `.dot` — your preference)
so we can revise it without re-drawing.

**Specification**

- **Format:** PNG, minimum 2000 px wide, legible at 100% zoom, light background.
  A dark-mode variant is welcome but optional.
- **Must show:**
  - The three tiers — Presentation (Streamlit, `127.0.0.1:8501`), Orchestration
    (LangGraph, bounded node set), Data & Integration (SQL Server
    `127.0.0.1:1433`, `FDE_TaskExposure`).
  - **Trust boundaries as explicit visual regions**, not just arrows. The
    boundary that matters most is agent-visible views vs agent-invisible base
    tables.
  - **The three principals** — `USR_FDE_RO`, `USR_FDE_LOAD`, `USR_FDE_SCORE` —
    labelled on the edges they authorise, so it is readable at a glance which
    component can reach which schema.
  - **The two independent computation paths** for exposure and for lag,
    visually distinct, converging only at the Review Gate. This is the single
    most important thing for a reader to take away.
  - **Offline ingestion separated from serving**, since a failed fetch must not
    degrade a live query.
  - **Egress-only external calls** — source APIs and the two model providers —
    with no inbound path.
  - The five `VW_*` views by name.
- **Should convey:** that no figure reaches the customer without a traceable
  path back to a hashed source artefact.
- **Please avoid:** a generic boxes-and-arrows stack diagram that would suit any
  RAG application. The security boundary and the twin computation paths are what
  make this design what it is; if those are not immediately visible, the diagram
  has not done its job.

### 8.3 Optional

If the review changes the design materially, a marked-up section list for the
TDD is more useful to us than prose — we will fold your changes back into
`docs/technical_design.md` directly.
