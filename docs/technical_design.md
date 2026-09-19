# Technical Design Document (TDD): Task Exposure & Adoption Lag Assistant

**Author:** Forward-Deployed Engineer
**Status:** Architecture Review complete — amendments applied, ready for P1
**Date:** September 2026
**Target environment:** Local Windows workstation, SQL Server Developer Edition

---

## Table of Contents

1. [System Architecture (HLD)](#1-system-architecture-hld)
   - 1.1 Architectural Overview
   - 1.2 Component Responsibilities
2. [Agent Orchestration (LLD)](#2-agent-orchestration-lld)
   - 2.1 State Management & Execution Loop
   - 2.2 Resiliency & Fallbacks
3. [Data & Security Model (LLD)](#3-data--security-model-lld)
   - 3.1 Evidence Security (VW_* view layer)
   - 3.2 Role-Based Access Control (RBAC)
   - 3.3 Immutable Auditing
4. [Deployment Strategy](#4-deployment-strategy)
   - 4.1 Infrastructure Topology
   - 4.2 Network Perimeter Security
5. [Appendix A: Resolved Decisions & Risks](#5-appendix-a-resolved-decisions--risks)
6. [Appendix B: Warehouse Schema](#appendix-b-warehouse-schema)

---

## 1. System Architecture (HLD)

The Task Exposure & Adoption Lag Assistant is a decoupled, three-tier analytical
platform designed to enable a business or finance analyst to interrogate the
exposure of a given occupation to LLM and agent substitution, and the timetable
over which that exposure is likely to be realised, through a natural language
interface.

The system answers one customer question — *which of our cost lines are exposed
to agent substitution, and on what timetable?* — and is architecturally
committed to answering it as **two separate quantities**. Exposure and timing are
routinely conflated in the market; the frame this project is built on holds that
the payoff from a general purpose technology arrives not with the machine but
with the reorganisation the machine permits, and the most-cited LLM exposure
study explicitly declines to forecast adoption timing. The architecture
therefore computes exposure and lag on **independent paths that never read each
other's output**.

### 1.1 Architectural Overview

The system relies on a stateless presentation layer, a state-machine-driven
orchestration engine, and a hardened data access layer in which the agent never
touches a base table.

```
┌─────────────────────────────────────────────────────────────────────┐
│  PRESENTATION TIER              localhost:8501                      │
│  Streamlit. Stateless. UI session state only.                       │
│  Renders: task exposure table · lag interval · calibration          │
│           statement · provenance panel (quote + page)               │
└───────────────────────────────▲─────────────────────────────────────┘
                                │ typed request / RoleVerdict response
┌───────────────────────────────┴─────────────────────────────────────┐
│  ORCHESTRATION TIER                                                 │
│  LangGraph state machine. Bounded node set, no free-form ReAct       │
│  loop over scoring.                                                  │
│                                                                      │
│    ┌──────────────┐   ┌──────────────┐   ┌──────────────┐          │
│    │ Intent &     │──▶│ Evidence     │──▶│ Task         │          │
│    │ Scope Node   │   │ Retrieval    │   │ Classifier   │          │
│    └──────────────┘   └──────────────┘   └──────┬───────┘          │
│                                                  │                   │
│    ┌──────────────┐   ┌──────────────┐   ┌──────▼───────┐          │
│    │ Synthesis    │◀──│ Review Gate  │◀──│ Deterministic│          │
│    │ Node         │   │ (Orchestr.)  │   │ Scoring Svc  │          │
│    └──────────────┘   └──────────────┘   └──────────────┘          │
│                                                                      │
│  ── agents classify and narrate; they never compute a score ──      │
└───────────────────────────────▲─────────────────────────────────────┘
                                │ SELECT on views only, USR_FDE_RO
┌───────────────────────────────┴─────────────────────────────────────┐
│  DATA & INTEGRATION TIER        SQL Server 127.0.0.1:1433            │
│  Database: FDE_TaskExposure                                          │
│                                                                      │
│  Agent-visible:   VW_ROLE_TASKS · VW_EXPOSURE_BENCHMARK              │
│                   VW_ADOPTION_CURVE · VW_CLAIM_EVIDENCE              │
│                   VW_INDUSTRY_METRIC                                 │
│  Agent-invisible: ref.* core.* score.* audit.*  (base tables)        │
│                                                                      │
│  Ingestion (offline, separate credential):                           │
│    API adapters   bea · bls · census · fred                          │
│    Doc adapters   onet(TSV) · exposure(XLSX) · btos(XLSX) · pdf      │
└─────────────────────────────────────────────────────────────────────┘
```

The acquisition and normalisation components are **already built**: 20 datasets
across four government APIs and 9 documents across four formats, all landed with
SHA-256 digests and normalised to typed Pydantic contracts. This document
specifies the warehouse, orchestration, security and delivery tiers.

### 1.2 Component Responsibilities

- **Presentation Tier:** Stateless Streamlit application. Manages UI session
  state only; all reasoning and all scoring are offloaded to the Orchestration
  Tier. Renders no figure it did not receive in a typed response, so the UI
  cannot become a source of numbers.

- **Orchestration Engine:** A LangGraph state machine. This component manages
  the execution lifecycle — scope validation, evidence retrieval, per-task
  semantic classification, invocation of the deterministic scoring service, and
  synthesis of a cited answer. It is deliberately **not** an open ReAct loop:
  the node set is fixed and the scoring node is not a model call.

- **Deterministic Scoring Service:** Pure deterministic Python, no external
  network and no model calls, versioned by `rubric_version`. It does connect to
  the local SQL Server instance under `USR_FDE_SCORE` to persist its output;
  calling it "no network" would be ambiguous. Holds `ExposureScorer`, `TacitnessPenalty`,
  `LagModel` and `Calibrator`. This is where the arithmetic lives, so that a
  model change cannot silently move a customer-facing quantity.

- **Data & Integration Tier:** Decoupled backend. The system strictly isolates
  the LLM/agent from the raw underlying data by exposing only flat, read-only
  database views accessed through a read-only role wrapper. Ingestion writes to
  base tables under a separate credential the agent runtime does not possess.

---

## 2. Agent Orchestration (LLD)

The orchestration tier ensures deterministic behaviour within a probabilistic
framework by using a state-machine architecture. The division of labour is
explicit: **the model makes categorical judgments about task semantics; Python
performs every calculation.**

| Node | Provider | Responsibility | Prohibited from |
|---|---|---|---|
| Intent & Scope | Anthropic | Resolve the requested occupation/sector to known SOC/NAICS codes; reject out-of-scope requests | Inventing a SOC code |
| Evidence Retrieval | — (tool) | Fetch tasks, benchmarks, adoption curve, claims via views | Returning unsourced rows |
| Task Classifier | OpenAI | Per task: routine/non-routine, cognitive/manual, tacitness flags, direction, with cited claim IDs | Assigning any numeric score |
| Deterministic Scoring | — (Python) | Category → exposure, tacitness penalty, lag interval, calibration | Calling a model |
| Review Gate | Anthropic | Verify every task score carries evidence and confidence; verify caveats non-empty; evaluate calibration; emit `pass`, `review_required` or `gate_rejected` | Overriding a computed number |
| Synthesis | OpenAI | Render the persisted verdict as customer prose | Introducing any figure absent from `score.*` |

Model identifiers are configurable by environment variable and are recorded per
call in the audit log, so a run is reproducible against the model that produced
it.

### 2.1 State Management & Execution Loop

The agent uses a LangGraph state object to maintain context throughout the
interaction. The state carries `run_id`, resolved scope, retrieved evidence,
per-task classifications and gate status — never raw credentials and never
partially-computed scores.

1. **Ingestion & Parsing:** The agent receives natural language input and
   resolves it to a scope tuple `(soc_code, naics_sector, geography)`. If the
   occupation cannot be resolved against `VW_ROLE_TASKS`, the run halts with an
   explicit out-of-scope response rather than substituting a near neighbour.

2. **Evidence Retrieval:** The agent queries the view layer for the task list,
   published exposure benchmarks, the sector adoption curve, and topic-matched
   claims. Retrieval precedes reasoning, so the model reasons over evidence it
   did not generate.

3. **Reasoning Loop:** For each task, the classifier emits a categorical
   judgment plus the claim IDs supporting it. Where the classifier reports low
   confidence or cannot cite evidence, the task is marked `unclear` and carried
   forward as such — it is not resolved by re-prompting until it agrees.

4. **Deterministic Scoring:** Classifications are passed to the scoring service,
   which returns `exposure_adjusted` per task, a role-level index, and a lag
   interval computed on a separate path from the adoption curve and the
   historical-lag claims. No model participates in this step.

5. **Review Gate:** The orchestrator checks that every persisted score has
   evidence and confidence, that `caveats` is non-empty, and that the run's
   sources are bound (§3.3). It then evaluates calibration against the published
   benchmark and emits one of three outcomes:

   | Outcome | Condition | Effect |
   |---|---|---|
   | `pass` | Within tolerance | Proceeds to synthesis |
   | `review_required` | Outside tolerance **with** a documented methodological explanation | Halts for human review; no automatic report |
   | `gate_rejected` | Outside tolerance **without** explanation, or any structural check failed | Run terminated, **no report produced** |

   The middle state exists because calibration *disagreement* and calibration
   *failure* are different things. Our estimand and the published benchmark's
   are not identical, so a large delta accompanied by strong evidence and a
   known methodological reason is a finding, not proof that the arithmetic is
   wrong. A binary gate would either suppress that finding or, if loosened to
   admit it, become decorative.

   The active threshold is recorded per run as `calibration_policy_version`,
   initially `provisional_v1` (±15 percentile points). It is an engineering
   bootstrap, not a validated criterion: the empirical distribution of
   deviations across occupations should be examined before it is locked.

6. **Synthesis:** Raw scoring output is synthesised into a cited, context-aware
   answer in which exposure and timetable are stated as separate findings, with
   their uncertainty.

### 2.2 Resiliency & Fallbacks

- **Graceful Degradation:** If an external API is unavailable at ingestion time,
  the system reports the affected series as stale, naming the last successful
  retrieval date, rather than interpolating or omitting silently. The BLS
  adapter already demonstrates the pattern: its v2 key is currently rejected, so
  it falls back to the keyless v1 endpoint and logs a WARNING on every run
  because the fallback narrows the available history.

- **Suppressed Data Is Not Zero:** Census suppresses small cells (`S`) and marks
  uncollected periods (`.`). Both are preserved as missing, never zero-filled.
  A suppressed estimate is absent information, not an absence of adoption.

- **Self-Correction, Bounded:** If a view query returns an error, the agent logs
  it and retries once with a narrowed predicate before escalating. Retries are
  capped; an agent that cannot retrieve evidence fails the run rather than
  proceeding without it.

- **Extraction Quality Guard:** PDF quote extraction is validated before use. A
  run-on token detector rejects quotes corrupted by the known pdfplumber
  spacing defect, so a plausible-but-wrong quotation cannot reach the customer.

- **No Silent Interpolation:** Where evidence is insufficient for a task or a
  period, the output states that it is insufficient. Degrading explicitly is a
  requirement, not a failure mode.

---

## 3. Data & Security Model (LLD)

Security is implemented at the physical database layer to mitigate prompt
injection risk. The principle is that the agent's authority should be bounded by
what its credential can do, not by what its instructions tell it to do.

### 3.1 Evidence Security (VW_* view layer)

The agent interacts solely with flat, read-only SQL views. Base tables in
`ref`, `core`, `score` and `audit` are not granted to the agent's role and are
not reachable from it. The base schema those views project from is specified in
Appendix B.

| View | Fields exposed |
|---|---|
| `VW_ROLE_TASKS` | `Task_ID, SOC_Code, Occupation, Statement, Task_Type, Importance, Weight_Source, Source_Doc_ID` |
| `VW_EXPOSURE_BENCHMARK` | `SOC_Code, Measure, Value, Percentile, Scale_Note, Source_Doc_ID` |
| `VW_ADOPTION_CURVE` | `Survey, Period_Start, Sector_Code, Question_Code, Answer_Label, Value, Unit, Is_Suppressed, Source_Doc_ID` |
| `VW_CLAIM_EVIDENCE` | `Claim_ID, Topic, Quote, Page, Doc_Title, Publisher, Is_Mirror, Source_Doc_ID` |
| `VW_INDUSTRY_METRIC` | `Provider, Series_ID, Industry_Code, Period, Value, Unit, Source_Doc_ID` |

**Every view exposes `Source_Doc_ID`.** This is not decoration: under the
append-only model (Appendix B) `source_doc_id` *is* the immutable version
identity of the artefact a row came from, and the run-to-source binding in
§3.3 can only be populated if the retrieval layer can see which document each
returned row resolves to. A view without it would make the reproducibility
guarantee unbuildable.

**Security principle:** by exposing only a flat, view-based schema, we
physically prevent the agent from executing `DROP`, `UPDATE`, `DELETE` or
`ALTER`, and prevent it from reaching any column not deliberately published.

**Design principle:** the view set is also a *scope* control. Of the 20 datasets
landed from the APIs, only those serving this use case are published as views.
Handing an agent every available table is how a confident answer gets built on
the wrong one.

Two view-level guarantees carry the project's guardrails into the data layer:

- `VW_CLAIM_EVIDENCE` always returns `Quote` and `Page` together, and surfaces
  `Is_Mirror`. The synthesis node may cite only what this view returned, which
  is the structural answer to fabricated citations: the model never has to
  recall a source, only select one it was handed.
- `VW_EXPOSURE_BENCHMARK` cannot return a value without its `Scale_Note`. These
  indices are standardised relative measures, not probabilities, and are
  meaningless without that statement.
- Every view returns `Source_Doc_ID`, so consumption can be recorded against an
  immutable, hash-identified artefact rather than inferred afterwards.

### 3.2 Role-Based Access Control (RBAC)

Database connections from the orchestration tier are established using the
`USR_FDE_RO` service account. This account lacks permission to write, to modify
schema, or to access any object outside the published views.

| Principal | Grants | Used by |
|---|---|---|
| `USR_FDE_RO` | `SELECT` on `VW_*` only. `DENY` on all base tables. No DDL. | Orchestration tier / agent runtime |
| `USR_FDE_LOAD` | `INSERT` on `ref`, `core`. `SELECT` everywhere. No `UPDATE`/`DELETE` on fact tables. | Offline ingestion scripts |
| `USR_FDE_SCORE` | `INSERT` on `score`, `audit`. `SELECT` on `ref`, `core`. | Deterministic scoring service |
| `USR_FDE_AUDIT` | `INSERT` on `audit.AgentAuditLog` only. No `SELECT`, `UPDATE` or `DELETE` on any application data. | Local audit adapter, on behalf of every orchestration node |

The scoring service holds a different credential from the agent runtime. This
matters: the agent can request a score, but cannot write one.

**Why a fourth principal.** Every orchestration node must emit an audit record,
but `USR_FDE_RO` cannot write and `USR_FDE_SCORE` belongs to the scoring
service. Earlier revisions of this document left that contradiction unresolved.
`USR_FDE_AUDIT` closes it without weakening the read-only surface. The
credential is held by a **local audit adapter**, not by node code, so no
orchestration node ever possesses a write credential of any kind — the nodes
call the adapter, and the adapter owns the connection.

`USR_FDE_LOAD` has lost `UPDATE`. Under the append-only model (Appendix B)
revised source data produces a new row rather than overwriting an existing one,
so ingestion has no legitimate reason to mutate a fact in place, and the grant
should reflect that.

Integrity constraints enforce the project's guardrails at the storage layer
rather than by convention:

- Every `core` row carries a `FOREIGN KEY` to `ref.source_document`. An
  unprovenanced fact is not representable.
- `score.role_verdict` carries `CHECK (LEN(caveats) > 0)`. A verdict with no
  stated caveats cannot be persisted.
- `core.extracted_claim` carries `CHECK (page >= 1)` and a non-null `quote`.
- `ref.source_document.is_mirror` flags third-party republication; two AIOE
  files in the current corpus are mirrors and are marked as such.

### 3.3 Immutable Auditing

Every decision cycle is committed to `AgentAuditLog` (append-only).

**Log entry:**
`{Timestamp, Run_ID, User_Prompt, Node_Invoked, Tool_Invoked, Tool_Raw_Output, LLM_Decision, Provider, Model, Prompt_Version, Input_Tokens, Output_Tokens, Duration_Ms, Status}`

Append-only is enforced two ways: `DENY UPDATE, DELETE ON AgentAuditLog` for
every application principal, and an `INSTEAD OF UPDATE, DELETE` trigger that
raises. The log is therefore a record of what happened, not a record of what the
system currently believes happened.

`Tool_Raw_Output` is stored unmodified. This is what makes a disputed figure
resolvable after the fact: the exact rows the model saw are recoverable, so a
wrong answer can be attributed either to the evidence or to the reasoning over
it.

#### Run-to-source binding

The audit blob is strong forensic evidence but a poor relational mechanism for
answering *which immutable source versions contributed to run X*. That question
is answered by an explicit binding table, `audit.run_source_binding`
(Appendix B.4).

Two design points matter:

- **No `source_version` column.** Under append-only, a revised artefact produces
  a new `ref.source_document` row, so `source_doc_id` *is* the version identity
  and its SHA-256 proves the content. A separate version column would duplicate
  that identity and create a second thing to keep consistent.
- **Bind on consumption, not availability.** A source is bound to a run when
  evidence from it actually participates in the result, not merely because it
  sat in the warehouse. This preserves the distinction between the evidence
  universe and the evidence that materially drove the answer. It is enforceable
  because every view exposes `Source_Doc_ID` (§3.1).

The traceability guarantee therefore reads:

> customer figure → `score.*` → run/source binding → immutable `core.*` /
> `ref.source_document` → SHA-256 hashed artefact

and for prose:

> claim → `Claim_ID` → verbatim quote + page + publisher

A companion table, `audit.quality_assertion`, records blocking load-time checks:
foreign-key resolution, load idempotency on source hash, percentages within
`[0,100]`, suppressed cells flagged rather than zeroed, quote page numbers
within document page counts, and run-on token detection on every extracted
quote.

---

## 4. Deployment Strategy

The system is deployed to a single local Windows workstation. There is no cloud
component. Provisioning is scripted — schema DDL, view definitions, role grants
and seed reference data are version-controlled and applied idempotently, so the
environment is rebuildable rather than hand-configured.

This is a deliberate fit for the customer domain rather than a limitation of
convenience: the target firms run SQL Server and T-SQL estates, so building
against a local SQL Server instance is closer to the real delivery environment
than a cloud-native store would be.

### 4.1 Infrastructure Topology

```
┌──────────────────────────────────────────────────────────────────┐
│  LOCAL WORKSTATION (Windows 11)                                  │
│                                                                   │
│   ┌────────────────────────┐                                     │
│   │ Browser                │  http://127.0.0.1:8501              │
│   └───────────┬────────────┘                                     │
│               │ loopback only                                     │
│   ┌───────────▼────────────┐                                     │
│   │ Streamlit App Process  │  presentation tier                  │
│   └───────────┬────────────┘                                     │
│               │ in-process call                                   │
│   ┌───────────▼────────────┐        ┌──────────────────────────┐ │
│   │ Orchestration +        │───────▶│ Anthropic API  (HTTPS)   │ │
│   │ Scoring Service        │───────▶│ OpenAI API     (HTTPS)   │ │
│   └───────────┬────────────┘        └──────────────────────────┘ │
│               │ ODBC Driver 18, USR_FDE_RO                        │
│   ┌───────────▼────────────┐                                     │
│   │ SQL Server Developer   │  127.0.0.1:1433                     │
│   │ DB: FDE_TaskExposure   │  loopback bind only                 │
│   └────────────────────────┘                                     │
│                                                                   │
│   ┌────────────────────────┐        ┌──────────────────────────┐ │
│   │ Offline Ingestion      │───────▶│ BEA · BLS · Census ·     │ │
│   │ (scheduled / manual)   │        │ FRED · O*NET · arXiv ·   │ │
│   │ USR_FDE_LOAD           │        │ NBER   (HTTPS, egress)   │ │
│   └────────────────────────┘        └──────────────────────────┘ │
│                                                                   │
│   Landing zone: data/raw · data/docs   (SHA-256 per artefact)     │
└──────────────────────────────────────────────────────────────────┘
```

Ingestion runs out-of-band from serving. A failed fetch therefore cannot degrade
a live query, and the warehouse is never mid-load while being read.

### 4.2 Network Perimeter Security

1. **Ingress (none public):** The Streamlit process binds to `127.0.0.1:8501`
   only. There is no listener on any routable interface, so there is no public
   attack surface. Remote access, if later required, is via SSH tunnel rather
   than by widening the bind address.

2. **Internal Communication:** SQL Server listens on `127.0.0.1:1433` with
   TCP/IP remote connections disabled in SQL Server Configuration Manager and a
   Windows Firewall inbound rule blocking 1433 on all profiles. The database is
   invisible to the local network and to the public internet.

3. **External communication:** HTTPS to the source APIs and the two model
   providers. Stated precisely — because responses obviously do return over
   these connections — **no externally initiated inbound connection is
   accepted; external traffic occurs only as responses over locally initiated
   outbound HTTPS sessions.** "Egress-only" is the shorthand, but the above is
   the security-accurate claim.

4. **Credential handling:** API keys and the SQL connection string are read from
   a gitignored `.env` by a loader that fails fast and names every missing key.
   Secrets are never logged; `AgentAuditLog` stores prompts and tool output but
   no credential material.

> **Outstanding remediation.** The four government API keys currently in `.env`
> have been exposed in a shared working directory during development and should
> be rotated before this project becomes portfolio-public. The BLS key
> additionally needs re-registration — it is presently rejected by the v2
> endpoint, which costs us the wider query window.

---

## 5. Appendix A: Resolved Decisions & Risks

The system is in ideation. The four open decisions were resolved at
architecture review; they are retained below with their reasoning, since each is
an assumption a customer is entitled to interrogate.

### 5.1 Resolved decisions

All four were resolved at architecture review (September 2026). They are kept
here with their reasoning rather than deleted, because each is an assumption a
customer is entitled to interrogate.

#### Decision 1 — Task weighting for SOC 13-2051 — **RESOLVED**

O\*NET publishes no ratings for this occupation: its task list is
analyst-written rather than survey-based, so there is no importance rating and
no Core/Supplemental split. This is a property of the source, not a missing
engineering feature.

> **Primary:** equal weighting, due to the absence of occupation-specific task
> importance ratings.
> **Robustness:** adjacent-SOC weighting (13-2099.01, Financial Quantitative
> Analysts) computed and reported separately; never silently substituted.

Equal weighting is coarse, and it is described as an **aggregation convention**
rather than a claim that every task is economically equally important.

The decisive argument against making borrowed ratings primary is that they are
*endogenous to the question*. Importing the importance structure of a
quantitative occupation would systematically overweight technical and
quantitative tasks — which would move the exposure result in precisely the
direction the system exists to measure. Equal weighting introduces fewer hidden
assumptions and is observable and reproducible.

The role index is therefore computed twice during validation. If the conclusion
materially changes between primary and sensitivity, that divergence becomes a
stated caveat rather than something buried inside the model.

`core.task.weight_source` records which convention produced a given row.

#### Decision 2 — Calibration tolerance — **RESOLVED (provisional)**

±15 percentile points, recorded per run as
`calibration_policy_version = provisional_v1`, feeding the three-state gate in
§2.1.

Explicitly a temporary engineering threshold, not a validated criterion. Our
methodology and the published benchmark are not the same estimand, and a gate
tuned too tightly would gradually turn the system into an elaborate mechanism
for reproducing somebody else's number. The empirical distribution of
deviations across occupations should be collected before the threshold is
locked.

#### Decision 3 — Lag model form — **RESOLVED**

**Do not fit a logistic curve.** Report the observed adoption trajectory,
historically grounded lag evidence, and an explicit `p10 / p50 / p90` interval.

Under two years of LLM-era adoption history — finance moving from 29.9% to
36.5% — cannot identify an S-curve saturation level. Inferring one would create
a visual impression of precision the data does not support. The chosen option is
the less impressive one; it is also the defensible one.

This reinforces the exposure/lag separation: exposure can be high while
organisational transformation remains slow. Logistic or Gompertz modelling is
revisited only once there is enough trajectory to identify curvature
empirically.

#### Decision 4 — Mirror verification — **RESOLVED**

| Run type | Policy |
|---|---|
| Development / internal | Unverified mirror permitted; `Is_Mirror` warning retained and surfaced |
| Customer-deliverable | Unverified mirror **blocks** the Review Gate |

`score.run.is_customer_deliverable` records the run type so the gate can
enforce this mechanically rather than by documentation. Since the system's
principal promise is provenance, a third-party copy must never silently become
the authoritative source — but development should not be blocked on it either.

### 5.2 Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Adoption data is sector-level (NAICS 52, pooling banking and insurance with securities) while the cost line is securities (NAICS 523) | **High** | Granularity mismatch stated in every output; never imply a 523-specific adoption rate. Not solvable by architecture — it is how the data is published. |
| Lag estimate over-claims precision from a short observation window | **High** | Resolved by decision 3: no curve fitting, intervals not points |
| Pre-LLM adoption vintages (ABS 2018/2020) mistaken for evidence about agents | Medium | `Survey` and period labelled on every observation; caveat mandatory |
| Agent emits a plausible unsourced figure | Medium | Synthesis restricted to `VW_CLAIM_EVIDENCE` output; `USR_FDE_RO` cannot write |
| Source revision silently changes what a past run saw | **High** | Resolved by B.0 append-only model plus `audit.run_source_binding` |
| Prompt injection via retrieved document text | Medium | Retrieved content is data, never instruction; agent authority bounded by credential, not by prompt |
| PDF extraction corrupts a quote | Medium | Run-on detector rejects suspect quotes; regression fixture in test suite |
| Mirror source diverges from publisher | Medium | `Is_Mirror` surfaced in the view; verification gate before delivery |

### 5.3 Delivery phases

| Phase | Deliverable | Depends on |
|---|---|---|
| **P0** *(complete)* | Acquisition + normalisation: 20 API datasets, 9 documents, typed corpus | — |
| **P1** | Append-only schema DDL, view layer (all five exposing `Source_Doc_ID`), four role grants, loader, quality assertions, `run_source_binding` | — *(unblocked)* |
| **P2** | Deterministic scoring service with golden tests — a defensible number, no agents | P1 |
| **P3** | LangGraph orchestration, view-backed tool surface, three-state Review Gate, audit adapter | P2 |
| **P4** | Streamlit presentation tier and provenance panel | P3 |
| **P5** | Calibration review, caveat audit, customer walkthrough | P4, decision 4 |

P2 precedes P3 deliberately. The system should produce a defensible number
*before* any agent is involved, so that the agents' contribution is measurable
rather than assumed.

### 5.4 Testing strategy

| Level | Coverage |
|---|---|
| Schema | Pydantic contracts reject empty task statements, quotes under 20 characters, `page < 1`, missing `scale_note` |
| Adapter | Per-format fixtures: 3-row TSV, small XLSX, 2-page PDF; includes a regression fixture for the run-on spacing defect |
| Loader | Idempotency on source hash — load the same artefact twice, assert row counts unchanged; load a *revised* artefact, assert new rows appear and prior rows are untouched |
| Reproducibility | Score a run, revise a source artefact, re-resolve the original run through `run_source_binding`, assert it still returns the original evidence |
| Domain | Golden cases for `ExposureScorer`, `TacitnessPenalty`, `LagModel`; deterministic, so exact assertions are appropriate. Role index asserted under both equal-weight and adjacent-SOC sensitivity |
| Calibration | Known-good benchmark fixture must place 13-2051 at the 87th percentile; all three gate outcomes exercised |
| Security | `USR_FDE_RO` write to any base table must fail; `AgentAuditLog` update must raise; `USR_FDE_AUDIT` `SELECT` on application data must fail |
| Guardrail | Verdict with empty `caveats` must be rejected at insert |
| Workflow | End-to-end smoke test on a 3-task fixture occupation against a local test database |

---

## What good looks like

A reviewer should be able to take any figure in the final output, follow it to a
row in `score`, follow that through `audit.run_source_binding` to the exact
immutable source versions that run consumed, follow those to rows in `core` and
to a SHA-256 hashed artefact in the landing zone, and — for any prose claim — to
a page number and a verbatim quote. The binding step is what makes the walk
survive a source revision: the evidence a past run saw is recoverable even after
the publisher changes the underlying data.

If that walk breaks anywhere, the architecture has failed, however good the
number looks.

---

## Appendix B: Warehouse Schema

The base tables the view layer projects from. Four schemas, separated by **who
may write to them** — the separation is the security boundary described in §3.2,
not merely organisation.

| Schema | Contents | Written by |
|---|---|---|
| `ref` | Slowly-changing reference data: occupations, sectors, source documents | `USR_FDE_LOAD` |
| `core` | Normalised facts from sources | `USR_FDE_LOAD` |
| `score` | Scoring engine and model output | `USR_FDE_SCORE` |
| `audit` | Run metadata, agent decision log, quality assertions | `USR_FDE_SCORE` |
| `audit.AgentAuditLog` | Agent decision trail (append-only) | `USR_FDE_AUDIT` |

### B.0 Persistence model: content-addressed and append-only

**Facts are never updated in place.** This is the single most consequential
change made at architecture review, and it exists because `MERGE` idempotency
and *reproducibility* are not the same requirement.

Consider: Census revises an adoption observation from 35.8 to 36.1. A natural-key
`MERGE` updates the existing row. A run scored last quarter still exists in
`score.*`, but the evidence underneath it has silently changed. The audit log
preserves the raw tool output, so the forensic record survives — but the
*relational* provenance chain no longer reconstructs the warehouse state that
run actually saw. The two records now disagree.

The model is therefore:

| Data | Strategy |
|---|---|
| Source artefacts | **Immutable snapshots** identified by SHA-256. A revised artefact is a *new* `ref.source_document` row, never an overwrite. |
| `core` facts and claims | **Append-only by source version.** Loading the same artefact again is a no-op because that `sha256` already exists; loading a revised artefact creates new rows. |
| Mutable reference entities | **Effective-dated / system-versioned** where the entity genuinely changes identity over time (`ref.occupation`). |
| `VW_*` views | Project the **latest valid version** for current analysis. |
| Historical runs | Resolve against the exact `source_doc_id` set recorded in `audit.run_source_binding`. |

Idempotency is therefore keyed on **source hash + natural key**, not on natural
key alone. `source_doc_id` carries version identity — there is deliberately no
separate `source_version` column, because that would duplicate the identity the
hash already establishes and create a second thing to keep consistent.

### B.1 Reference and provenance

```
ref.source_document
  doc_id                      NVARCHAR(64)     PK
  title                       NVARCHAR(500)    NOT NULL
  publisher                   NVARCHAR(300)    NOT NULL
  url                         NVARCHAR(1000)   NOT NULL
  format                      NVARCHAR(16)     NOT NULL   -- pdf|xlsx|tsv|csv|api
  sha256                      CHAR(64)         NOT NULL
  bytes                       BIGINT
  retrieved_at                DATETIME2        NOT NULL
  provenance_note             NVARCHAR(MAX)
  is_mirror                   BIT              NOT NULL DEFAULT 0
  verified_against_publisher  BIT              NOT NULL DEFAULT 0

ref.occupation                                   -- system-versioned temporal table
  soc_code                    NVARCHAR(16)     PK
  title                       NVARCHAR(300)    NOT NULL
  onet_version                NVARCHAR(16)
  domain_source               NVARCHAR(64)                -- Incumbent|Analyst|Occupational Expert
  has_onet_ratings            BIT              NOT NULL   -- 0 for 13-2051; see Appendix A decision 1

ref.naics_sector
  sector_code                 NVARCHAR(8)      PK
  label                       NVARCHAR(300)    NOT NULL
  level                       TINYINT          NOT NULL   -- 2=sector, 3=subsector
```

`ref.occupation` is system-versioned because occupation metadata changes between
O\*NET releases, and a run must be reproducible against the metadata that was
current when it executed.

### B.2 Core facts

```
core.task                                        -- append-only by source version
  task_id                     NVARCHAR(32)     PK
  soc_code                    NVARCHAR(16)     NOT NULL FK -> ref.occupation
  statement                   NVARCHAR(1000)   NOT NULL
  task_type                   NVARCHAR(32)     NULL       -- Core|Supplemental|NULL
  importance                  DECIMAL(4,2)     NULL       -- 1-5; NULL when unrated
  relevance_pct               DECIMAL(5,2)     NULL
  weight_source               NVARCHAR(32)     NOT NULL   -- onet|adjacent_soc|equal
  source_doc_id               NVARCHAR(64)     NOT NULL FK -> ref.source_document

core.exposure_estimate                           -- published external benchmarks
  estimate_id                 BIGINT IDENTITY  PK
  soc_code                    NVARCHAR(16)     NOT NULL
  measure                     NVARCHAR(64)     NOT NULL   -- AIOE_language_modeling|...
  value                       DECIMAL(12,6)    NOT NULL
  percentile                  DECIMAL(5,2)     NULL
  scale_note                  NVARCHAR(MAX)    NOT NULL   -- CHECK (LEN(scale_note) > 0)
  source_doc_id               NVARCHAR(64)     NOT NULL FK
  UNIQUE (soc_code, measure, source_doc_id)

core.adoption_observation
  observation_id              BIGINT IDENTITY  PK
  survey                      NVARCHAR(32)     NOT NULL   -- BTOS|ABS
  period_label                NVARCHAR(16)     NOT NULL
  period_start                DATE             NULL
  sector_code                 NVARCHAR(8)      NULL FK -> ref.naics_sector
  question_code               NVARCHAR(16)     NOT NULL
  answer_label                NVARCHAR(200)    NOT NULL
  value                       DECIMAL(8,3)     NULL       -- NULL when suppressed
  unit                        NVARCHAR(16)     NOT NULL DEFAULT 'percent'
  is_suppressed               BIT              NOT NULL DEFAULT 0
  source_doc_id               NVARCHAR(64)     NOT NULL FK
  is_current                  BIT              NOT NULL DEFAULT 1
  UNIQUE (survey, period_label, sector_code, question_code, answer_label,
          source_doc_id)                        -- version-aware: append, never overwrite
  CHECK (value IS NULL OR value BETWEEN 0 AND 100)

core.extracted_claim                             -- append-only; claim_id is version-scoped
  claim_id                    NVARCHAR(200)    PK  -- includes source_doc_id, so a
                                                   -- re-extraction under a revised
                                                   -- artefact is a new claim, not an edit
  topic                       NVARCHAR(100)    NOT NULL
  quote                       NVARCHAR(MAX)    NOT NULL   -- verbatim, never paraphrased
  page                        INT              NOT NULL CHECK (page >= 1)
  note                        NVARCHAR(500)
  source_doc_id               NVARCHAR(64)     NOT NULL FK
  -- FULLTEXT INDEX ON (quote): evidence retrieved by meaning, not by scan

core.industry_metric                             -- BEA / FRED / BLS timeseries
  metric_id                   BIGINT IDENTITY  PK
  provider                    NVARCHAR(16)     NOT NULL
  series_id                   NVARCHAR(64)     NOT NULL
  industry_code               NVARCHAR(16)     NULL
  period                      DATE             NOT NULL
  value                       DECIMAL(18,6)    NULL
  unit                        NVARCHAR(64)
  source_doc_id               NVARCHAR(64)     NOT NULL FK
  is_current                  BIT              NOT NULL DEFAULT 1
  UNIQUE (provider, series_id, industry_code, period, source_doc_id)
```

`value` is nullable on `adoption_observation` by design: Census suppresses small
cells and marks uncollected periods, and a suppressed estimate is missing
information, not zero. `is_suppressed` distinguishes the two.

### B.3 Scoring output

```
score.run
  run_id                      UNIQUEIDENTIFIER PK
  started_at                  DATETIME2        NOT NULL
  finished_at                 DATETIME2        NULL
  git_sha                     CHAR(40)         NOT NULL
  config_hash                 CHAR(64)         NOT NULL
  rubric_version              NVARCHAR(16)     NOT NULL
  calibration_policy_version  NVARCHAR(32)     NOT NULL   -- e.g. provisional_v1
  is_customer_deliverable     BIT              NOT NULL DEFAULT 0
  status                      NVARCHAR(16)     NOT NULL
      -- running|passed|review_required|failed|gate_rejected
  notes                       NVARCHAR(MAX)

score.task_score
  run_id                      UNIQUEIDENTIFIER NOT NULL FK -> score.run
  task_id                     NVARCHAR(32)     NOT NULL FK -> core.task
  exposure_raw                DECIMAL(5,3)     NOT NULL   -- 0-1, pre-tacitness
  tacitness                   DECIMAL(5,3)     NOT NULL   -- 0-1 penalty
  exposure_adjusted           DECIMAL(5,3)     NOT NULL
  direction                   NVARCHAR(16)     NOT NULL   -- augment|substitute|unclear
  confidence                  NVARCHAR(16)     NOT NULL   -- high|medium|low
  rationale                   NVARCHAR(MAX)    NOT NULL
  evidence_claim_ids          NVARCHAR(MAX)    NULL
      CHECK (evidence_claim_ids IS NULL OR ISJSON(evidence_claim_ids) = 1)
  model                       NVARCHAR(64)     NOT NULL
  prompt_version              NVARCHAR(16)     NOT NULL
  PRIMARY KEY (run_id, task_id)

score.role_verdict
  run_id                      UNIQUEIDENTIFIER PK FK -> score.run
  soc_code                    NVARCHAR(16)     NOT NULL
  exposure_index              DECIMAL(5,3)     NOT NULL
  exposure_percentile         DECIMAL(5,2)     NULL
  lag_years_p10               DECIMAL(4,1)     NOT NULL
  lag_years_p50               DECIMAL(4,1)     NOT NULL
  lag_years_p90               DECIMAL(4,1)     NOT NULL
  lag_basis                   NVARCHAR(MAX)    NOT NULL   -- which observations drove it
  augmentation_share          DECIMAL(5,3)     NOT NULL
  weight_source               NVARCHAR(32)     NOT NULL
  caveats                     NVARCHAR(MAX)    NOT NULL CHECK (LEN(caveats) > 0)
  CHECK (lag_years_p10 <= lag_years_p50 AND lag_years_p50 <= lag_years_p90)

score.calibration
  run_id                      UNIQUEIDENTIFIER NOT NULL FK -> score.run
  benchmark_measure           NVARCHAR(64)     NOT NULL
  benchmark_percentile        DECIMAL(5,2)     NOT NULL
  our_percentile              DECIMAL(5,2)     NOT NULL
  delta                       DECIMAL(5,2)     NOT NULL
  within_tolerance            BIT              NOT NULL
  outcome                     NVARCHAR(24)     NOT NULL   -- pass|review_required|gate_rejected
  explanation                 NVARCHAR(MAX)    NULL
  PRIMARY KEY (run_id, benchmark_measure)
  CHECK (outcome <> 'review_required' OR LEN(explanation) > 0)
```

The two `CHECK` constraints on `role_verdict` are the project's guardrails made
structural: a verdict cannot be stored without stated caveats, and a lag
interval cannot be stored inverted.

### B.4 Audit

```
audit.AgentAuditLog                              -- append-only
  entry_id                    BIGINT IDENTITY  PK
  timestamp                   DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
  run_id                      UNIQUEIDENTIFIER NULL
  user_prompt                 NVARCHAR(MAX)
  node_invoked                NVARCHAR(64)
  tool_invoked                NVARCHAR(64)
  tool_raw_output             NVARCHAR(MAX)               -- stored unmodified
  llm_decision                NVARCHAR(MAX)
  provider                    NVARCHAR(16)
  model                       NVARCHAR(64)
  prompt_version              NVARCHAR(16)
  input_tokens                INT
  output_tokens               INT
  duration_ms                 INT
  status                      NVARCHAR(16)
  -- DENY UPDATE, DELETE to all application principals
  -- plus INSTEAD OF UPDATE, DELETE trigger that raises

audit.run_source_binding                         -- which sources a run actually consumed
  run_id                      UNIQUEIDENTIFIER NOT NULL FK -> score.run
  source_doc_id               NVARCHAR(64)     NOT NULL FK -> ref.source_document
  usage_type                  NVARCHAR(32)     NOT NULL
      -- task_source | exposure_benchmark | adoption_evidence
      -- | claim_evidence | industry_metric
  first_used_at               DATETIME2        NOT NULL
  PRIMARY KEY (run_id, source_doc_id, usage_type)

audit.quality_assertion
  assertion_id                BIGINT IDENTITY  PK
  run_id                      UNIQUEIDENTIFIER NULL
  check_name                  NVARCHAR(100)    NOT NULL
  target                      NVARCHAR(200)    NOT NULL
  passed                      BIT              NOT NULL
  observed                    NVARCHAR(500)
  checked_at                  DATETIME2        NOT NULL
```

### B.5 SQL Server features used deliberately

| Feature | Why |
|---|---|
| Append-only inserts keyed on **source hash + natural key** | Idempotent *and* reproducible. A destructive `MERGE` would give the first without the second — see B.0 |
| `FOREIGN KEY` to `ref.source_document` on every `core` table | Makes an unprovenanced fact unrepresentable rather than merely discouraged |
| `CHECK (LEN(caveats) > 0)` | A caveat-free verdict cannot be persisted |
| `ISJSON` constraint | Evidence ID arrays stay machine-readable |
| `FULLTEXT INDEX` on `core.extracted_claim.quote` | The agent retrieves evidence by meaning; no external vector store needed at this scale |
| System-versioned temporal table on `ref.occupation` | Reproducibility across O\*NET releases |
| `audit.run_source_binding` | Answers "which immutable sources produced this figure" relationally, rather than by parsing an audit blob |
| Filtered index on `is_current` | Keeps `VW_*` latest-version projection cheap as versions accumulate |
| Four logins with disjoint grants | §3.2 — the boundary is the credential, not the prompt; `USR_FDE_AUDIT` is INSERT-only on the log |
| `DENY UPDATE, DELETE` + trigger on the audit log | Append-only in fact, not by convention |
