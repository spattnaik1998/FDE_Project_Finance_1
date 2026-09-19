# Build Plan

**Project:** Task Exposure & Adoption Lag Assistant
**Date:** 19 September 2026
**Status:** Planning — no implementation until this plan is approved
**Governing documents:** `CLAUDE.md` (charter), `docs/technical_design.md` (TDD)

---

## 1. Purpose of this document

The TDD says *what* to build. This says *in what order*, *how each piece is
proven*, and *when it is allowed to be called done*.

Every work item below follows one loop, without exception:

```
   BUILD  →  TEST THOROUGHLY  →  FINALIZE  →  PUSH TO GITHUB
```

"Finalize" is not a formality. A work item is finalized only when its
acceptance criteria are demonstrably met, its tests are green, and the
documents that describe it have been updated. Nothing is pushed before that,
and nothing moves to the next item while the previous one is half-done.

---

## 2. Correction to the current status

I reported "P1 complete" after building the database. That was **overstated**.

TDD Phase P1 covers *"append-only schema DDL, view layer, four role grants,
loader, quality assertions, run_source_binding"*. The schema, views, roles,
constraints and reference seed are built and verified. **The loader is not
built, and the warehouse currently contains zero facts:**

| Table | Rows |
|---|---|
| `ref.source_document` | 0 |
| `core.task` | 0 |
| `core.exposure_estimate` | 0 |
| `core.adoption_observation` | 0 |
| `core.extracted_claim` | 0 |
| `core.industry_metric` | 0 |

So the first workstream below finishes P1 rather than starting P2.

### What genuinely is done

| | Deliverable | Evidence |
|---|---|---|
| **P0** | 20 API datasets, 9 documents, typed Pydantic corpus | `data/raw/_manifest.csv`, `data/interim/corpus.json` |
| **P1a** | 15 tables, 5 views, 4 roles, 30 CHECK, 14 FK, temporal table, append-only trigger | `scripts/setup_database.py` — 46 idempotent batches |
| **P1a** | Guardrails proven adversarially | `scripts/verify_database.py` — 17/17 |
| — | Both model providers verified live | `gpt-6-astra` and `claude-opus-5` both return 200 |

---

## 3. Working agreements

### 3.1 The loop, in detail

| Stage | What it means | Gate to pass |
|---|---|---|
| **Build** | Implement one work item. Small modules, type hints, docstrings on public functions, per the charter. | Code exists and runs |
| **Test** | Unit tests for logic; adversarial tests for anything claimed to be a guardrail; an integration test where a boundary is crossed. | All green, and the *negative* cases genuinely fail |
| **Finalize** | Update the TDD or README if behaviour changed. Record the decision in `CLAUDE.md` if a judgment call was made. | Docs match code |
| **Push** | Feature branch → commit → PR or merge to `main`. | Branch clean, no secrets |

### 3.2 Definition of done

A work item is done when **all** of these hold:

1. Acceptance criteria in this document are met and demonstrated, not asserted.
2. Tests exist and pass, including at least one test that would fail if the
   feature regressed.
3. Anything the TDD claims is *structural* is proven by a test that tries to
   violate it.
4. No secret, key, or credential is in the diff.
5. Docs updated where behaviour changed.
6. Pushed on its own branch with a specific commit message.

### 3.3 Git workflow

- Branch per work item: `feat/<phase>-<slug>`, e.g. `feat/p1-warehouse-loader`
- Commits are coherent and specific — no `wip`, no `fixes`
- `main` stays green; nothing merges with failing tests
- **`.env` must never be committed.** It is already in `.gitignore`; Workstream 0
  verifies this before the first push rather than after

### 3.4 Testing standard

Per the charter's minimum — schema validation tests, tool unit tests with
mocks, a workflow smoke test — plus two standards this project adds:

- **Adversarial tests for guardrails.** A guardrail that cannot be
  demonstrated failing is one nobody should trust. `verify_database.py` is the
  pattern to follow.
- **Determinism tests for L4.** The scoring service is pure, so exact
  assertions are appropriate. Golden cases, not tolerance ranges.

---

## 4. Workstreams

Nine workstreams. Dependencies are strict: nothing starts before its
predecessor is *finalized*.

```
  W0  Repo hygiene ─┐
                    ├─→ W1 Loader ─→ W2 Scoring ─→ W3 Providers ─┐
  (environment)  ───┘                                            │
                                                                 ├─→ W5 Nodes
                                     W4 Tools + binding ─────────┘     │
                                                                       ▼
                                              W6 Graph ─→ W7 Report ─→ W8 UI
```

---

### W0 — Repo hygiene and first push

**Why first:** the GitHub repo is being created now, and the first commit is
the one most likely to leak a secret.

| # | Item | Acceptance criteria |
|---|---|---|
| 0.1 | Verify `.gitignore` covers `.env`, `data/raw/`, `data/interim/`, `data/docs/`, `__pycache__` | `git status` shows no secret and no large data file staged |
| 0.2 | Add `requirements.txt` pinning the actual installed versions | Fresh `pip install -r` reproduces the environment |
| 0.3 | Register `ANTHROPIC_API_KEY` in `config.MODEL_KEYS`; point Review Gate and Intent nodes at `MODEL_ORCHESTRATOR` | `load_keys(include_models=True)` returns six keys |
| 0.4 | Decide where the three reference PDFs live (`reference/` vs project root) | Root contains only project files |
| 0.5 | Initial commit and push | `main` exists on GitHub, no secrets in history |

**Also flag, not block:** all six credentials have been present in a shared
working directory during development. They should be rotated before the repo
becomes public. The OpenAI and Anthropic keys are the two with real spend.

**Commits:** `chore: add requirements and verify gitignore`,
`feat: register anthropic credential and model config`

---

### W1 — Warehouse loader *(completes P1)*

**Goal:** move the landing zone and the typed corpus into SQL Server under the
append-only model, and prove a source revision does not disturb a past run.

| # | Item | Acceptance criteria |
|---|---|---|
| 1.1 | `src/warehouse/session.py` — connection factory, one place for the connection string, credential selected by role | Connects as the correct principal; no connection string duplicated |
| 1.2 | `src/warehouse/loader.py` — register artefacts into `ref.source_document` with SHA-256 from the landing zone | 9 documents + API datasets registered; digests match `data/docs/_documents.json` |
| 1.3 | Fact loaders for `task`, `exposure_estimate`, `adoption_observation`, `extracted_claim`, `industry_metric` | 26 tasks, 774 estimates, 126 adoption observations, 21 claims loaded |
| 1.4 | Idempotency on **source hash + natural key** | Load twice → row counts unchanged |
| 1.5 | Revision handling | Load a mutated artefact → new `source_doc_id`, new rows, prior rows untouched and still `is_current` resolvable |
| 1.6 | `src/warehouse/quality.py` — blocking load-time assertions into `audit.quality_assertion` | FK resolution, percentages in range, suppressed-not-zeroed, page ≤ document page count, run-on token detection |
| 1.7 | Suppressed-cell handling end to end | A `S` cell arrives as `value IS NULL, is_suppressed = 1`, never 0 |

**Tests:** loader idempotency; revision-then-reload; every quality assertion
firing on deliberately bad input; a view returning `Source_Doc_ID` for every row.

**Risk to watch:** `core.extracted_claim.claim_id` must be version-scoped. Our
current corpus generates IDs from `source_doc_id:topic:page:index`, which
already satisfies this — but it must be asserted, not assumed.

**Commits:** `feat: add warehouse session and source registration`,
`feat: load typed corpus facts append-only`, `test: loader idempotency and revision handling`

---

### W2 — Deterministic scoring service *(P2)*

**Goal:** a defensible number with **no agent involved**. This ships before any
model is wired in, so the agents' contribution is measurable rather than assumed.

| # | Item | Acceptance criteria |
|---|---|---|
| 2.1 | `ExposureScorer` — Acemoglu–Autor matrix position → exposure in [0,1] via a fixed, reviewable lookup | Mapping fits on one screen; golden cases exact |
| 2.2 | `TacitnessPenalty` — Polanyi discount, multiplicative, stated | High-tacitness task is discounted; the discount is reported, not hidden |
| 2.3 | Role index — **equal-weight primary** plus **adjacent-SOC (13-2099.01) sensitivity** | Both computed; divergence surfaced as a caveat; `weight_source` recorded |
| 2.4 | `LagModel` — **no curve fitting.** Observed trajectory + historical range → p10/p50/p90 with `lag_basis` naming the observations used | Refuses to emit an interval narrower than the evidence supports; reads adoption + claims only, never exposure |
| 2.5 | `Calibrator` — three-state: `pass` / `review_required` / `gate_rejected`, `provisional_v1` = ±15 points | All three outcomes exercised; `review_required` without explanation rejected at insert |
| 2.6 | Run lifecycle — create `score.run`, persist scores and verdict, close out status | A complete run persists and satisfies every CHECK constraint |

**Tests:** golden cases per component; **an independence test asserting the lag
path cannot read the exposure result** (the design's central claim); calibration
fixture placing 13-2051 at the 87th percentile; a verdict with empty caveats
rejected.

**The independence test is the most important test in the project.** If exposure
and lag are not provably independent, the differentiator is gone.

**Commits:** `feat: add exposure scorer and tacitness penalty`,
`feat: add lag model with no curve fitting`, `feat: add three-state calibrator`,
`test: assert exposure and lag paths are independent`

---

### W3 — Provider adapters

**Goal:** isolate both SDKs behind one interface so no provider detail leaks
across the codebase, per the charter.

| # | Item | Acceptance criteria |
|---|---|---|
| 3.1 | `src/providers/base.py` — one interface: structured completion, tool-enabled completion | Callers never import `openai` or `anthropic` directly |
| 3.2 | OpenAI adapter on **`/v1/responses`** with `reasoning.effort` | Established by probing: function tools do **not** work on `/v1/chat/completions` for `gpt-6-astra`, and `reasoning_effort='none'` is rejected |
| 3.3 | Anthropic adapter for Intent & Scope and Review Gate | Cross-provider independence preserved: the gate is not the same model that produced the work |
| 3.4 | Retry, timeout, structured logging with `run_id` | Transient failure retried; permanent failure raises a domain exception |
| 3.5 | Token and cost accounting | Spend per run reportable |

**Tests:** mocked adapters for unit tests; one live smoke test per provider,
skippable without credentials; schema-violation handling when a model returns
malformed structured output.

**Commits:** `feat: add provider interface and openai responses adapter`,
`feat: add anthropic adapter for orchestration nodes`

---

### W4 — View-backed tools and run-source binding

**Goal:** the agent's entire data surface, plus the mechanism that makes
reproducibility real rather than aspirational.

| # | Item | Acceptance criteria |
|---|---|---|
| 4.1 | Six read tools over the five views | Every tool returns `Source_Doc_ID` with each row |
| 4.2 | **Consumption capture** → `audit.run_source_binding` | A source is bound when evidence *participates*, not when merely available |
| 4.3 | Audit adapter holding `USR_FDE_AUDIT` | No node holds a write credential; nodes call the adapter |
| 4.4 | Tool scope enforcement | A tool reaching outside the five views fails |

**Tests:** each tool against seeded data; binding populated only for consumed
sources; **a privilege test asserting the read-only principal cannot write to
any base table**; audit-log update raising.

**Blocked by:** the four SQL logins need mixed-mode auth. Until then, tests run
under the developer credential and the privilege tests are marked expected-skip
— which must be recorded honestly rather than quietly passing.

**Commits:** `feat: add view-backed tool surface`,
`feat: capture run source bindings on consumption`, `test: tool scope and privilege isolation`

---

### W5 — Orchestration nodes

**Goal:** the model-driven nodes, each narrow, each unable to compute a number.

| # | Item | Acceptance criteria |
|---|---|---|
| 5.1 | Intent & Scope (Anthropic) | Resolves SOC/NAICS; **refuses** an unresolvable occupation rather than substituting a neighbour |
| 5.2 | Task Classifier (`gpt-6-astra`, strict `json_schema`) | Emits categorical judgments with cited claim IDs; **never a numeric score**; low confidence carried forward as `unclear` rather than re-prompted into agreement |
| 5.3 | Review Gate (Anthropic) | Checks evidence, confidence, non-empty caveats, source binding, calibration; emits one of three outcomes |
| 5.4 | Synthesis (`gpt-6-astra`) | Cites only what `VW_CLAIM_EVIDENCE` returned; introduces no figure absent from `score.*` |

**Tests:** classifier output validated against the Pydantic contract; a
**fabrication test** asserting synthesis output contains no numeral absent from
the persisted verdict; gate rejection producing no report; an out-of-scope
request halting cleanly.

**Commits:** one per node, plus `test: assert synthesis cannot introduce unsourced figures`

---

### W6 — LangGraph assembly

| # | Item | Acceptance criteria |
|---|---|---|
| 6.1 | Fixed node set, typed state object | No open ReAct loop; state carries no credentials |
| 6.2 | Twin paths: exposure via classifier, lag direct from adoption + claims | Graph topology asserts the independence in W2 |
| 6.3 | `gate_rejected` terminates the run | No report produced; status persisted |
| 6.4 | End-to-end run on SOC 13-2051 | A complete `RoleVerdict` with provenance |

**Tests:** full workflow smoke test on a 3-task fixture occupation against a
test database; graph-topology test asserting no edge from the exposure path
into the lag path.

**Commits:** `feat: assemble langgraph orchestration`, `test: end-to-end workflow smoke`

---

### W7 — Report and provenance

| # | Item | Acceptance criteria |
|---|---|---|
| 7.1 | Markdown report in the TDD's seven-section structure | Exposure and lag stated as **separate** findings |
| 7.2 | Provenance appendix | Every source, digest, quote and page |
| 7.3 | Traceability walk | Any figure → `score` → binding → `core` → hashed artefact |
| 7.4 | Limitations section | NAICS 52-vs-523 mismatch, equal-weight convention, pre-LLM vintages, short adoption window |

**Tests:** a **traceability test** that walks every figure in a generated
report back to a hashed artefact and fails if the walk breaks anywhere. This is
the test that decides whether the architecture achieved its purpose.

**Commits:** `feat: generate technical report with provenance appendix`,
`test: assert full traceability of every reported figure`

---

### W8 — Presentation tier

| # | Item | Acceptance criteria |
|---|---|---|
| 8.1 | Streamlit app, loopback only, stateless | Binds `127.0.0.1:8501`; renders no figure it did not receive |
| 8.2 | Exposure table, lag interval, calibration statement, provenance panel | Quote + page visible per claim |
| 8.3 | Mirror and caveat surfacing | Unverified mirror flagged in the UI |

**Tests:** UI renders a persisted verdict without recomputing anything; no
database access from the presentation tier.

**Commits:** `feat: add streamlit presentation tier`

---

## 5. Environment prerequisites

Tracked separately because they are not code and both need your authorisation.

| # | Prerequisite | Needed by | Impact if deferred |
|---|---|---|---|
| E1 | **Mixed-mode authentication** — registry change + SQL Server service restart affecting 26 other databases | W4 privilege tests | Tests run under the developer credential; the security model is built but unproven at runtime |
| E2 | **Full-Text Search** install | W4 claim retrieval | `search_claims` falls back to `LIKE`; acceptable for 21 claims, not beyond |
| E3 | **Graphviz binary** | Diagram regeneration | `Architecture_V1.png` keeps its mislabelled edge and predates the append-only change |
| E4 | **Credential rotation** | Before the repo is public | Six keys have been in a shared directory |

---

## 6. Ordering rationale

**Why the loader before scoring.** The scoring service reads from views. Golden
tests could use fixtures, but the append-only and revision behaviour can only
be proven against a real warehouse, and that behaviour is the architect's
principal amendment.

**Why scoring before any agent.** TDD §5.3. If the deterministic path produces a
defensible number alone, the agents' contribution is measurable. If agents land
first, we will never know which half of the system is doing the work.

**Why tools and providers before nodes.** Nodes are thin by design. Building
them before their dependencies exist would push logic into prompts, which the
charter explicitly forbids.

**Why the UI last.** It is the only component that cannot change a number, so it
carries the least risk and earns the least priority.

---

## 7. Risks to this plan

| Risk | Mitigation |
|---|---|
| The independence of exposure and lag erodes under implementation pressure | W2's independence test is written **before** the lag model, not after |
| `gpt-6-astra` behaviour is not fully characterised — it is past my knowledge cutoff | Every capability established by probing the live API; two constraints already found this way |
| Scope creep into the three sibling projects | Their data is landed but out of scope. Build this concretely; extract a framework only when project #2 actually arrives |
| The classifier's categories prove too coarse to carry the signal | Surfaced during W2 golden-case review, before agents are involved. This was the architect's open question 7 and remains genuinely unresolved |
| Privilege tests stay skipped and the security model ships unproven | E1 is tracked as a blocking prerequisite for W4's finalization, not an optional extra |

---

## 8. What this plan deliberately does not include

- Any of the three sibling projects (tail-index, productivity J-curve,
  distributional tier analysis)
- A shared orchestration framework. The architect recommended building reusable
  primitives now; with one use case unbuilt that is speculative abstraction.
  Build project #1 concretely and extract the framework when #2 arrives and we
  know what actually generalises.
- Vector retrieval. `FULLTEXT` first, with a retrieval benchmark before
  reaching for vector infrastructure.
- Cloud deployment. Local SQL Server is the target environment, deliberately.

---

## 9. Immediate next step

**W0.1 — verify `.gitignore` excludes `.env` and the data directories, before
the first push.** Everything else waits on your approval of this plan.
