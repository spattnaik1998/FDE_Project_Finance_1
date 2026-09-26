# Task Exposure & Adoption Lag — data layer

Project #1 of the FDE portfolio series. See `CLAUDE.md` for the charter.

This stage does one thing: pull every dataset the four government APIs give us,
land it as CSV, and understand what is actually in it. Architecture comes after.

## Layout

```
src/
  config.py            credential loading, fails fast and names what is missing
  http_client.py       one retry/timeout/logging policy for every provider
  sources/
    bea.py             GDP by Industry, NIPA/Fixed Assets
    bls.py             timeseries, with v2 -> v1 fallback
    census.py          ABS, BDS, CBP
    fred.py            series search, observations, metadata
scripts/
  probe_apis.py        one minimal live call per provider
  fetch_all.py         the dataset inventory -> data/raw/*.csv + _manifest.csv
  analyze_data.py      findings -> notes/data_exploration.md + data/interim/
data/raw/              20 fetched datasets (gitignored)
data/interim/          tidy analysis tables (gitignored)
notes/                 data_exploration.md
```

## Running it

```bash
python scripts/probe_apis.py     # verify credentials
python scripts/fetch_all.py      # ~2 min, writes data/raw/
python scripts/analyze_data.py   # writes notes/data_exploration.md
```

## Credentials

Six keys in `.env` (gitignored), read by `src/config.py`, which tolerates
`KEY=value`, `KEY = 'value'` and `KEY: value`.

### Resolution precedence — most specific source wins

1. An environment variable **explicitly set for this process** — someone
   exported it for this run, so they meant it.
2. The project's **`.env`**.
3. An **inherited** user- or machine-scope environment variable.

This is deliberately *not* plain environment-beats-file. A machine-scope
variable is system-wide configuration; a project's `.env` is narrower and more
intentional, so the project wins. `config.persisted_env_value()` reads the
Windows registry (unprivileged) to tell an inherited variable from a
deliberately exported one, and `config.key_sources()` reports which source each
credential came from.

The rule exists because it was needed: a stale machine-level `OPENAI_API_KEY`
shadowed a valid `.env` entry and surfaced as an opaque provider 401, with no
fix available short of Administrator rights. `.env` now wins and logs that it
did.

**Optional permanent cleanup.** The stale machine variable is harmless now but
still misleading. To remove it, from an **elevated** PowerShell:

```powershell
[Environment]::SetEnvironmentVariable('OPENAI_API_KEY', $null, 'Machine')
```

Then restart any open shell. Nothing in the project depends on this.

| Key | Status |
|---|---|
| `BEA_API_KEY` | working |
| `CENSUS_API_KEY` | working |
| `FRED_API_KEY` | working |
| `BLS_API_KEY` | **rejected by BLS v2** — the adapter falls back to keyless v1 |

The BLS fallback costs real capability: v1 allows 25 series per query, a
10-year window and 25 queries/day, against v2's 50 series, 20 years and 500
queries/day. Re-register free at `data.bls.gov/registrationEngine` and the
adapter will use v2 automatically — `bls.key_is_valid()` probes before choosing.

## What we have

20 datasets across four providers. `data/raw/_manifest.csv` records, per
dataset, the analytical purpose it serves, row/column counts, fetch duration
and any error — so the inventory explains itself.

The load-bearing ones:

- **Census ABS 2018 + 2020** — technology adoption by sector, and firms' own
  reports of how technology use changed headcount and skill level. The 2020
  module splits AI into machine learning, NLP, machine vision and voice.
- **Census BDS, 1978–2023** — firm entry, exit and job reallocation for NAICS 52.
- **Census CBP 2022** — establishments, employment and payroll by size class.
- **BEA GDP-by-Industry** — value added, gross output and the compensation share
  of value added, with securities (523) broken out separately.
- **FRED** — productivity, labour share, finance employment, IP investment.
- **BLS** — securities-industry employment, hours and earnings.

## Document layer (unstructured sources)

Nine documents across four formats, normalised into one typed `Corpus`
(`src/documents/schemas.py`): `Task`, `ExposureEstimate`, `AdoptionObservation`,
`ExtractedClaim`. Downstream code never sees "a PDF" or "a spreadsheet".

```bash
python scripts/fetch_documents.py   # -> data/docs/ + _documents.json
python scripts/build_corpus.py      # -> data/interim/corpus.json
python scripts/analyze_corpus.py    # -> notes/corpus_exploration.md
```

| Source | Format | Gives |
|---|---|---|
| O*NET 29.3 (statements, ratings, occupations) | TSV bulk | 26 tasks for SOC 13-2051 |
| Felten/Raj/Seamans AIOE | XLSX | 774 occupation exposure scores |
| Census BTOS national + sector | XLSX (wide) | biweekly AI-use rates, 2023-2026 |
| Eloundou et al. 2303.10130 | PDF | exposure benchmark + authors' caveats |
| Brynjolfsson/Rock/Syverson w25148 | PDF | the adoption-lag argument, quantified |

Every document carries a SHA-256 digest and a provenance note. Every
prose-derived claim carries a verbatim quote and page number -- paraphrase is
where fabricated citations come from, so extraction here is purely mechanical.

### Known issues in the document layer

- **PDF spacing.** pdfplumber's default `x_tolerance=3` merges words on tightly
  kerned justified text ("economicimpactwithout..."). Fixed at 1.5, with a
  run-on detector that rejects any quote still showing the defect.
- **Keyword extraction is noisy.** Roughly a third of extracted claims are
  dedication lines, title blocks or false matches. Acceptable because noise is
  visible and discardable; fabrication would not be.
- **Two AIOE files are third-party mirrors**, not the publisher's copies, and
  are flagged as such in the provenance ledger.

## Database and warehouse loader (P1 — complete)

SQL Server `FDE_TaskExposure` on `LAPTOP-FO95TROJ`. DDL is version-controlled
and idempotent; re-running rebuilds rather than migrates.

```bash
python scripts/setup_database.py       # apply 01-05
python scripts/verify_database.py      # adversarial guardrail tests
python scripts/setup_database.py --include-logins   # after mixed-mode auth is on
```

| Script | Contents |
|---|---|
| `01_database_and_schemas.sql` | Database + `ref` / `core` / `score` / `audit` |
| `02_tables.sql` | 15 tables, 30 CHECK, 14 FK, temporal `ref.occupation`, append-only audit trigger |
| `03_views.sql` | The five `VW_*` agent-visible views |
| `04_roles_and_permissions.sql` | Four roles with disjoint grants |
| `05_seed_reference.sql` | NAICS sectors and target occupations |
| `06_logins_and_users.sql` | **Deferred** — needs mixed-mode auth |
| `07_fulltext.sql` | **Deferred** — needs the Full-Text feature |

Permissions live on **roles**, not logins, so the whole security model is built
and testable before the SQL logins exist. `db_fde_ro` holds 5 grants against
20 denies; `db_fde_audit` holds 1 grant against 17 denies.

`scripts/verify_database.py` tries to violate every guardrail the TDD claims is
structural and asserts the database refuses — 17/17 pass, including empty
caveats, inverted lag intervals, suppressed-cell-with-a-value, sub-20-character
quotes, unprovenanced facts, unexplained calibration disagreement, and
UPDATE/DELETE on the audit log.

### Loading

```bash
python scripts/load_warehouse.py   # landing zone + corpus -> SQL Server
python -m pytest                   # 104 tests
```

Facts are **append-only** and content-addressed. Idempotency keys on source
hash plus natural key, so re-running the loader inserts nothing; a *revised*
artefact becomes a new `ref.source_document` row with new facts, and the prior
rows stay exactly as the run that consumed them saw. `is_current` is demoted
rather than deleted, so the `VW_*` views show the latest version while history
remains queryable.

| Table | Rows |
|---|---|
| `ref.source_document` | 29 (9 documents + 20 API datasets) |
| `core.task` | 26 |
| `core.exposure_estimate` | 774 |
| `core.adoption_observation` | 126 |
| `core.extracted_claim` | 21 |
| `core.industry_metric` | 16,057 |

Ten blocking quality assertions run after every load and record their outcome
in `audit.quality_assertion` — pass or fail, so a load that silently degraded
is distinguishable from one that never ran.

### Test suite

104 tests across six files, against an isolated `FDE_TaskExposure_Test`
database rebuilt from the production DDL (a test schema that drifts from the
real one proves nothing about the real one).

| File | Covers |
|---|---|
| `test_loaders.py` | Idempotency, revision handling, suppressed cells, percentile computation |
| `test_registry.py` | SHA-256 content addressing, version detection, digest drift |
| `test_quality.py` | Every assertion driven to failure deliberately |
| `test_guardrails.py` | Structural claims the TDD makes, each violated on purpose |
| `test_views.py` | The five-view agent surface and its guarantees |
| `test_integration.py` | The real loaded warehouse against the exploration's findings |

Worth noting what the quality tests revealed: seven of the ten assertions are
*also* enforced by a CHECK or FOREIGN KEY constraint, so the bad row cannot be
inserted at all. For those the constraint is the real guarantee and the
assertion is defence in depth. Three — run-on quote detection, duplicate
current versions, and views exposing `Source_Doc_ID` — have no constraint
behind them and carry real weight on their own.

### Environment prerequisites — two remain, both needing elevation

**1. Mixed-mode SQL authentication** (blocks runtime privilege isolation)

```powershell
# from an ELEVATED PowerShell, in the project root
powershell -ExecutionPolicy Bypass -File scripts\enable_sql_auth.ps1
```

The script sets `LoginMode = 2`, restarts the SQL Server service, generates a
strong password per principal into `.env`, and applies
`sql/06_logins_and_users.sql`. **It restarts the instance**, dropping open
connections to every other database on it.

Until it runs, the loader and scoring service connect as the developer, so the
`DENY` grants are built but unproven at runtime. `session.py` logs a WARNING on
every such run, and `tests/test_privileges.py` — 25 assertions covering all
four principals — **skips with that reason rather than passing under a
credential that would satisfy anything.** Running the script turns those skips
into real assertions.

**2. Full-Text Search** (needed for `VW_CLAIM_EVIDENCE` retrieval in W4, not
before)

```powershell
# needs the SQL Server 2022 installation media; the local bootstrap has no
# cached feature payload
& "C:\Program Files\Microsoft SQL Serverp\Setup Bootstrap\SQL2022\setup.exe" `
    /ACTION=Install /FEATURES=FullText /INSTANCENAME=MSSQLSERVER `
    /IACCEPTSQLSERVERLICENSETERMS /QS
```

`sql/07_fulltext.sql` detects its absence and skips cleanly, so nothing breaks
in the meantime; `search_claims` falls back to `LIKE`, which is adequate for 21
claims and not beyond.

**3. BLS API key** (not elevation — free re-registration at
`data.bls.gov/registrationEngine`). The current key is rejected by v2, so the
adapter falls back to keyless v1 and logs it: 25 series per query, a 10-year
window, 25 queries/day against v2's 50 / 20 years / 500. `bls.key_is_valid()`
probes first, so a working key is picked up with no code change.

## Deterministic scoring service (P2 — complete)

```bash
python scripts/run_scoring.py      # control run: no agent involved
python -m pytest                   # 234 tests
```

Pure Python, no network, no model calls, versioned by `rubric_version`. Ships
**before** any agent so the agents' contribution is measurable rather than
assumed.

| Module | Responsibility |
|---|---|
| `schemas.py` | Typed contracts. `TaskClassification` carries **no numeric field** — if a score could be supplied there, a model could set it |
| `exposure.py` | Acemoglu–Autor matrix lookup + Polanyi tacitness discount + role aggregation |
| `lag.py` | Adoption lag from diffusion evidence and historical precedent. Imports nothing from the exposure path |
| `calibration.py` | Three-state gate against the published benchmark |
| `baseline.py` | Keyword classifier — the control the model must beat |
| `run.py` | Run identity, verdict assembly, persistence, source binding |

### The rubric

| | Cognitive | Manual |
|---|---|---|
| **Routine** | 0.90 | 0.20 |
| **Non-routine** | 0.55 | 0.05 |

Tacitness discounts multiplicatively — low 0.00, medium 0.25, high 0.55 — and
the discount is **reported separately**, not folded into one number. Manual
work scores low because this is LLM exposure, not automation exposure in
general: a language model does not move boxes.

### Control run result (13-2051.00, 26 tasks)

```
EXPOSURE index   0.555          (equal weighting)
sensitivity      0.518 – 0.594  (bound under 13-2099.01)
LAG years        p10 5.0 | p50 10.1 | p90 30.0   (curve fitted: False)
observation win  0.88 years
calibration      review_required
```

Most exposed: "Create client presentations of plan details" (0.900). Least:
"Confer with clients to restructure debt" (0.247) and "Develop and maintain
client relationships" (0.405) — both on the high tacitness discount. The rubric
discriminates rather than saturating, which was the reason for choosing this
occupation.

### Three refusals built into the design

1. **No curve is fitted.** The observed window is 0.88 years. `lag.py` holds
   the interval at least 15 years wide below a 2-year window, and says so in
   the basis. Even handed a deliberately narrow prior it widens.
2. **Calibration is not identifiable on one occupation.** A percentile is a
   rank within a distribution and this run scored one occupation, so the
   outcome is `review_required` with a stated reason rather than a silent pass.
3. **The sensitivity is a bound, not a point.** No task-level mapping exists
   between 13-2051 and 13-2099.01, so both extremal assignments of the
   neighbour's importance distribution are computed. The true weighted index
   lies in that range under *any* mapping.

### Exposure and lag are provably independent

`tests/test_independence.py` enforces it at three levels: behavioural (varying
the exposure result leaves the lag byte-identical), interface (`estimate_lag`
has no parameter an exposure could pass through), and **structural** — the test
parses `lag.py` with `ast` and fails if it imports or references the exposure
path. The structural check is the one that survives refactoring, because
introducing the coupling means also deleting the test.

It was written before `lag.py` existed and failed for the right reason first.

## Provider adapters (W3 — complete)

```bash
python -m pytest                 # 310 tests (6 hit live APIs)
python -m pytest -m "not live"   # 304 tests, no credentials needed
```

One interface over two providers. Callers ask for a structured completion and
get a `ModelResponse`; they never import `openai` or `anthropic`, never learn
which mechanism produced the structure, and never see an endpoint URL. A test
parses every module outside `src/providers/` and fails if a vendor SDK is
imported.

| Stage | Vendor | Model |
|---|---|---|
| Intent & Scope | Anthropic | `MODEL_ORCHESTRATOR` |
| Task Classifier | OpenAI | `MODEL_CLASSIFIER` |
| Review Gate | Anthropic | `MODEL_REVIEW_GATE` |
| Synthesis | OpenAI | `MODEL_WRITER` |

The split is the cross-provider independence property from TDD §2 — the gate
grading the classifier's work is a different vendor from the one that produced
it — and it has a test rather than a comment.

### Two mechanisms, one interface

Both established by probing the live API, not from documentation:

- **OpenAI** uses `/v1/responses` with a strict `json_schema`. Not
  `/v1/chat/completions`: function tools are unsupported there for
  `gpt-6-astra`, and the documented workaround (`reasoning_effort: 'none'`) is
  itself rejected for this model.
- **Anthropic** has no `json_schema` response format. Structure comes from
  declaring one tool whose `input_schema` *is* the contract and forcing it with
  `tool_choice`; the tool input is the answer.

Neither adapter falls back to parsing prose when structure fails. A schema
obtained by guessing at free text is not a schema, so `SchemaViolation` is
raised with the offending payload attached.

### Two model profiles, and a gate between them

`MODEL_PROFILE` selects the models for the two OpenAI stages. One switch rather
than four variables, because a half-switched configuration — an economy
classifier feeding a full-price writer — saves little and is hard to reason
about after the fact.

| | Classifier / writer | Effort | Use |
|---|---|---|---|
| `economy` *(default)* | `gpt-5.4-mini` | `low` | Development, tests, rehearsal |
| `full` | `gpt-6-astra` | `medium` | A run intended for a client |

Both were established against this project's own classifier schema on the live
API, not from documentation: strict `json_schema` on `/v1/responses` works for
each, and a full 28-call graph run takes **25s on `economy` against ~90s on
`full`**.

**The saving is price and latency, not tokens.** A full run costs 32,189 tokens
on `economy` and 30,047 on `full` — the schema fixes the shape of the answer, so
a smaller model does not write less. The profile documentation says so rather
than letting the word "economy" imply a token reduction it does not deliver.

**What `economy` costs in quality, measured rather than assumed.** On the same 26
tasks, `gpt-6-astra` resolved direction on 14 (54%) and `gpt-5.4-mini` on 5
(19%), carrying the other 21 as `unclear`. Both refused to output `substitute`
anywhere, and the lag interval was byte-identical. So the cheaper model is a
sound test harness and a visibly weaker analyst on the one judgment this project
argues the model earns its cost on.

Which is why **the Review Gate blocks an `economy` run from being marked
customer-deliverable**, in the same shape as the unverified-mirror policy:
blocking on a deliverable run, informative on an internal one, so nobody's
development loop is obstructed. The economy profile exists to make rehearsal
cheap, and its runs persist like any other — the check is the only thing between
"we tested on the cheap model" and "we handed a client a figure from it".

One consequence to know about: `score.cohort_index` is keyed on
`(cohort, classifier, rubric_version)`, so an `economy` run finds no reference
set scored by `gpt-5.4-mini` and its calibration reads as *not identifiable*
until the cohort is re-scored on that model. That is the key doing its job —
ranking our index against a distribution some other model produced would not be
a comparison — but it does mean the profiles are not interchangeable mid-analysis.

### Cost accounting withholds rather than guesses

Token counts are facts the API reports and are always recorded. **Cost is
reported only when a price is configured** via `PRICE_<MODEL>_INPUT` /
`_OUTPUT`. `gpt-6-astra` postdates this project's reference material, so its
price is not known here; the ledger returns `cost_usd: None` with
`cost_status: "unpriced_models: gpt-5.4-mini"` rather than a total that silently
omits half the calls.

### Retry

Retries 408/409/425/429 and 5xx with exponential backoff plus jitter; raises
immediately on any other 4xx, because a 400 will be 400 again. `run_id` and
`stage` travel on every call through `CallContext` and appear in every log line.

## Tool surface (W4 — complete)

Six read tools over five views. The agent's entire data surface, and the point
at which provenance stops being a convention.

| Tool | Returns |
|---|---|
| `get_tasks(soc_code)` | Task statements + weighting convention. **Refuses** an unknown occupation rather than substituting a neighbour |
| `get_exposure_benchmarks(soc_code, measure?)` | Published indices, always with `Scale_Note` |
| `get_adoption_curve(sector, question?, answer?, include_suppressed?)` | Diffusion trajectory. Suppressed cells are NULL, never zero |
| `search_claims(topic?, text?, limit?)` | Verbatim quote + page + publisher + mirror status |
| `get_industry_metric(series_id, industry?, start?, end?)` | One economic series |
| `get_source_document(doc_id)` | Digest, publisher, mirror status — registers no consumption |

### Three properties enforced, not assumed

**Scope.** `ALLOWED_VIEWS` is a whitelist checked before execution, so a tool
cannot be made to read a base table even by a caller that wants it to. A
second test parses `evidence.py` with `ast` and fails if any tool SQL names a
base table.

**Provenance.** Every row carries `Source_Doc_ID`, and a row without one raises
`ProvenanceMissing` rather than being returned — it could otherwise appear in
an output with no traceable origin.

**Consumption.** `ConsumptionTracker` records sources when a tool *returns* a
row carrying them. That operational definition is stated explicitly in the
module: a stricter reading (what the model demonstrably reasoned over) is
unobservable, a looser one binds the whole warehouse, and returned-to-the-caller
is the narrowest boundary that can be measured. A tool returning zero rows
binds nothing.

### The audit adapter

`AuditAdapter` holds `USR_FDE_AUDIT` and is the only thing in the system that
writes to `audit.AgentAuditLog`. **No orchestration node holds a write
credential of any kind** — nodes call `emit`, the adapter owns the connection.
`tool_raw_output` is stored unmodified so a disputed figure is attributable to
the evidence or to the reasoning over it.

### Control run through the tool surface

`scripts/run_scoring.py` now reads through the same six tools the agent will
use, so the binding and audit trail are exercised now rather than first
appearing in W5:

```
EXPOSURE index   0.541          sensitivity 0.498 – 0.584
LAG years        p10 5.0 | p50 10.1 | p90 30.0
Sources bound:   4 bindings across 4 distinct sources
Audit entries:   6
```

`search_claims` falls back to `LIKE` because Full-Text Search is not installed,
and **says so in the result** — "lexically different phrasings of the same
idea will be missed." Adequate at 21 claims, not beyond.

## Orchestration nodes (W5 — complete)

```bash
python scripts/run_orchestrated.py            # full run, real models
python scripts/run_orchestrated.py --limit 4  # cheaper trial
```

Four model nodes plus a deterministic retrieval step, each a plain function
over `RunState` so it is testable alone. Graph assembly is W6.

| Node | Vendor | Refusal it enforces |
|---|---|---|
| 1. Intent & Scope | Anthropic | An unpublished occupation halts the run; **never** substitutes a neighbour |
| 2. Evidence Retrieval | — (tools) | No tasks retrieved → fail, rather than an index over zero tasks |
| 3A. Task Classifier | OpenAI | Categories only; invented citations dropped; `unclear` carried forward, not re-prompted |
| 4. Review Gate | Anthropic | Cannot upgrade a rejected calibration; an unavailable gate rejects |
| 5. Synthesis | OpenAI | No figure or citation absent from the evidence; two bad drafts → **no narrative** |

### Did the model beat the baseline?

The plan's standard was that the classifier must beat keyword matching
*meaningfully*, or it is adding cost rather than judgment. Both were run over
the same 26 tasks:

| | Baseline (keyword) | Model (`gpt-6-astra`) |
|---|---|---|
| Exposure index | 0.541 | **0.384** |
| Direction resolved | 0 of 26 | **14 of 26** |
| …as `augment` | 0 | 14 |
| …as `substitute` | 0 | **0** |
| Low confidence | 26 of 26 | **0** |
| Cited evidence | 0 | **14** |
| Lag interval | 5.0 / 10.07 / 30.0 | 5.0 / 10.07 / 30.0 |

**Yes, on the field that matters.** The baseline cannot tell augmentation from
substitution and says so on every task; the model resolves it on 54% of them
and cites evidence while doing it. Note the zero in the `substitute` row — the
model independently landed on the augmentation reading, which is what the
survey prior supports (47.2% of adopting finance firms reported skill levels
rising against 1.6% falling).

The lower index is a *consequence*, not the improvement: the model applies
higher tacitness than keyword matching, which is the direction Polanyi's bound
predicts. It is not evidence that 0.384 is "more accurate" than 0.541, and the
report does not claim that.

Cost of the difference: **28 model calls, 30,047 tokens, 3.4 minutes.**

### The lag is identical, in a live run

`baseline lag identical: True`. Exposure and lag are computed on independent
paths, and swapping the entire classification layer left the lag interval
byte-identical. The property is enforced structurally in
`tests/test_independence.py` and now demonstrated end to end.

### The gate articulated its own reasoning correctly

It emitted `review_required` and named the cause: *"our percentile is None, so
the benchmark percentile of 86.82 has no counterpart to compare against. This
is an unidentifiable comparison, not a numeric disagreement."* That is exactly
the distinction the three-state gate exists for. **No narrative was produced**,
because `review_required` does not yield a report.

### The fabrication guard

`nodes/figure_guard.py` builds an allow-set from the verdict, the task scores
and the evidence rows, extracts every number from a draft, and rejects anything
left over. Calibrated in both directions: it catches an invented percentage, an
invented year and an invented headcount, and does **not** fire on "three
caveats", on 0.54 rounded from 0.541, or on a share quoted as a percentage. A
guard that fires on ordinary English gets switched off, and a guard that is off
catches nothing.

## Graph assembly (W6 — complete)

```bash
python scripts/run_graph.py --topology-only   # print the graph; no model calls, no cost
python scripts/run_graph.py                   # full run through LangGraph
```

W5 chained the nodes by hand. W6 hands control to LangGraph, so the two claims
the architecture rests on stop being prose and become topology:

```
__start__          -> intent_scope
intent_scope       -> evidence_retrieval
evidence_retrieval -> exposure_path        \  the fan-out
evidence_retrieval -> lag_path             /
exposure_path      -> assemble_verdict     \  the fan-in
lag_path           -> assemble_verdict     /
assemble_verdict   -> review_gate
review_gate        -> synthesis
synthesis          -> __end__
```

`src/graph/build.py` exposes `edges()`, `reaches()` and
`concurrent_write_conflicts()` read from the **compiled** graph, so the tests
assert against what was actually built rather than a hand-drawn picture of it.

### Independence, now enforced at a fourth level

`tests/test_independence.py` already proved it behaviourally, through the
interface, and structurally by parsing `lag.py` with `ast`. The graph adds:

- `reaches(EXPOSURE_PATH, LAG_PATH)` is `False`, and so is the reverse — there
  is no path through the graph from one to the other.
- `NODE_WRITES` declares field ownership, and
  `concurrent_write_conflicts()` is asserted empty. The two branches run in the
  same superstep; a shared field would couple them through the state object
  even though neither module imports the other.

### Termination is structural, not conditional prose

`route_after_gate` sends anything other than a clean pass to `END`. A gated run
therefore cannot reach synthesis, so **an unreviewed figure has no path to a
customer-facing narrative**. The edge is invisible in the drawn topology —
LangGraph omits conditional edges targeting `END` — so the test asserts it
through the routing function, which is the authority.

### The documented limitation, asserted

`test_production_cannot_currently_reach_a_pass` pins the honest state of the
system: with one scored occupation there is no percentile of our own, so
calibration returns `review_required`, the gate cannot upgrade it, and no
report is produced. Scoring several occupations is what unblocks this — not a
change to the gate. The test exists so that limitation cannot drift out of the
documentation unnoticed.

## Report and provenance (W7 — complete)

```bash
python scripts/generate_report.py                    # latest run with a verdict
python scripts/generate_report.py --out report.md
python scripts/generate_report.py --run-id <uuid> --quiet
```

Seven sections, rendered **deterministically from persisted rows** — no model
is involved. Exposure and lag appear as two separate findings and are never
combined into a single score.

### Two artefacts, not one

The TDD withholds the *automatic narrative* on `review_required`. It does not
withhold the analysis from the human the run was halted for — "halts for human
review" presupposes something to review. So:

| Artefact | Produced when | Written by |
|---|---|---|
| Synthesis **narrative** | `pass` only | the model, figure-guarded |
| Technical **report** | any run reaching a verdict | deterministic renderer |

The gate protects model prose. Rendered data carries no fabrication risk, so
gating it would withhold the analysis from the reviewer without buying
anything. What the report does instead is lead with the standing: a run that
did not calibrate says so in section 1, before any figure.

### Provenance by construction, not by inspection

`report/figures.py` is the only way to put a number into the document.
`emit()` refuses to render a figure that cannot name a source document, so an
unprovenanced number is not "caught" — it is unrenderable.

That is the opposite of `nodes/figure_guard.py`, and deliberately so. There a
*model* writes the prose, so numbers must be audited after the fact. Here the
renderer is ours, so provenance is a precondition. A failure in the guard means
a model fabricated; a failure here means the renderer has a bug.

Numbers inside persisted prose (`lag_basis`, caveats, publisher strings) are
registered too, against the column that holds them. Exempting prose would have
made the scan meaningless — anything could be smuggled in as a sentence.

### The traceability walk

`report/provenance.py` walks every figure:

```
figure -> score.* row -> audit.run_source_binding -> ref.source_document -> SHA-256
```

Four break modes, reported separately because they mean different things:

| Break | Meaning |
|---|---|
| `unregistered` | a number in the document the renderer never registered |
| `unbound` | a figure citing a source **this run** never consumed |
| `unhashed` | a bound source with no usable digest |
| `unverified_mirror` | chain complete, but terminates at an unchecked copy |

Only the first three break the walk. A mirror is a qualification: it blocks
`customer_deliverable` without invalidating the document.

**On the real warehouse: 126 figures traced, 0 unregistered, 0 unbound,
0 unhashed, 1 unverified mirror** (the Felten AIOE benchmark, which is a known
mirror and is flagged in section 1 rather than buried).

The `unregistered` check reads the **rendered text**, not the registry, so it
catches a renderer that bypasses the registry entirely. Checking the registry
against itself would be the vacuous version of this test.

### Verbatim quotes reach the customer

The appendix resolves claim evidence to its **verbatim quote and page** — the
project's rule that a prose-derived claim is never paraphrased, applied at the
point it matters. It also states its own binding granularity:
`audit.run_source_binding` records the *artefact* a tool returned a row from,
not the individual quote read, so the trace is source-level and says so.
Implying a finer trace than exists would be the subtle form of overclaiming.

### Two bugs the walk caught that review would not have

1. **Truncation manufactured a figure.** The renderer registered the full
   quote but rendered a shortened one, so cutting "2025" mid-token left a bare
   "25" in the document that was in no source. Registration now happens on the
   *shortened* string, and `_shorten` falls back to a whitespace boundary.
2. **A benchmark cited without a binding.** The report wanted to print the
   benchmark percentile on a run that never bound an `exposure_benchmark`
   source. The figure is now withheld and the absence stated — a number that
   cannot be traced to an artefact *this run consumed* is unsupported for this
   run even when it is correct in general.

Code spans are skipped, because they hold identifiers (`doc_id`, digests, run
ids) rather than findings — and `test_no_code_span_is_purely_numeric` closes
the loophole that would otherwise open, so a figure cannot be smuggled in by
wrapping it in backticks.

## Presentation tier (W8 — complete)

```bash
python scripts/run_ui.py                  # http://127.0.0.1:8501
python scripts/verify_stack.py --layer ui # gateway, runtime, loopback binding
```

Eight sections in the browser, rendering a run that already happened. The finding
leads, its standing is immediately under it, provenance last, exposure and lag
never combined.

### Palette and type, from the two sites named in the brief

Read off their stylesheets rather than described from memory. What Boston
University and Red Key Solutions agree on turned out to be more useful than where
they differ: both are overwhelmingly white, both carry a single red, both set text
in a warm near-black rather than pure black, and both keep colour off the body of
the page entirely.

| Token | Hex | From | Used for |
|---|---|---|---|
| `--paper` | `#FFFFFF` | both | the page |
| `--panel` | `#F5F6F8` | BU off-white (RKS `#F3F4F8`) | finding panel, request card |
| `--ink` | `#1C1B1A` | Red Key near-black | body text, **data bars** |
| `--navy` | `#0C2537` | BU secondary | headings, meter fill, focus ring |
| `--red` | `#CC0000` | **BU Red** | masthead rule, section marks, primary button |
| `--red-deep` | `#C31420` | Red Key | button hover, "not fit to use" |

Red appears in exactly four places and nowhere else. In particular **the data bars
are ink, never red** — a bar in the brand's red reads as an alarm, which tells the
reader something about the number that the number does not say.
`test_the_spine_is_not_drawn_in_the_brand_colour` parses those two declarations and
fails if either takes the accent.

Type inverts the usual pairing deliberately: **Libre Franklin**, an American
institutional gothic in the register both reference sites are written in, sets the
masthead and headings, because a headline here is signage. **Source Serif** carries
the argument, because a case a reader has to weigh should read like prose and not
like an interface. **IBM Plex Mono** with tabular figures sets every quantity.

### The exposure spine

Each row of the per-task table carries a short ink rule scaled to that task's net
exposure, so the **shape** of the distribution is visible instead of being
assembled from 26 decimals. That shape is the claim the rubric exists to support —
it discriminates rather than saturates, which is why this occupation was chosen.

The widths are computed in the gateway, not the presentation tier, and join the
traced figure set like any other number: a layer that can compute can produce a
figure that is on no source, and the test that walks the page for untraceable
numbers would have nothing to catch it with. Building it also closed a real blind
spot — `displayed_strings` skipped list values inside a block payload, so the
widths would have reached the page without passing the scan.

### It has to read as written, not generated

Nineteen of our own schema keys were on the page — `review_required`,
`provisional_v2_cohort`, `felten_aioe_language_modeling`,
`brynjolfsson_productivity_j_curve` — in captions, in the caveat list, and as the
"used for" and "subject" columns of the provenance tables. A reader sees
underscored tokens wrapped around numbers and correctly concludes nobody wrote the
page.

`app/copy.py` now holds a vocabulary map: a named phrase where the identifier
deserves one, and a general fallback otherwise, because a bare `replace("_", " ")`
gives "Not prediction" and "J curve definition" — readable, and not written. The
provenance table shows each source's **title** rather than its filing key, and the
lag disclosure states how many historical passages the interval rests on rather
than printing their claim IDs.

It is a vocabulary map, not a rewrite: the findings are untouched, and the
downloadable technical report still carries every identifier verbatim, because a
figure under dispute has to be traceable by its real key. The one exempt line on
the page is the audit footer, and `test_the_audit_footer_still_carries_the_real_keys`
stops that exemption from becoming a way to hide everything.

Writing this also caught me inventing two figures — a citation year and a
population count typed into a copy string, neither traceable to a source this run
consumed. The traceability check rejected them and they were removed rather than
exempted.

### A document, not a dashboard

The first version styled Streamlit's widgets and lost. Every `st.metric` and
`st.dataframe` brings its own container, its own margin and its own idea of a
heading, so the result read as a tinted dashboard however good the colours were —
and a dashboard is for monitoring something you already understand, while this
reader is being persuaded.

The block list is unchanged — it is still the presentation model and still what
the tests inspect — but `app/document.py` composes it into **one HTML document**,
emitted in one call per run. What that buys: real `<table>` markup with numerals
right-aligned in a tabular face instead of a data grid; `<details>` for the method
disclosures instead of expander chrome; a three-card summary band above the fold;
a masthead that reads as a letterhead; Source Serif for the argument, IBM Plex
Sans for labels, IBM Plex Mono for every quantity; and a print stylesheet, because
a research note gets printed.

Two block kinds stay widgets and are listed rather than assumed: the question box,
and the download button, which needs a real HTTP response that markup cannot
produce. `document.render_block` raises on anything that is neither rendered nor
declared a widget, and the dispatcher's dead branches were deleted rather than
left unreachable.

Streamlit is now a loopback host, which is all TDD 4.1 asks of it. A Node or
Next.js pivot was considered and rejected: what made the page look like Streamlit
was its widgets, not its presence, and routing is the only thing a pivot would
have added.

Because this module builds HTML by concatenation it is the one injection surface
in the project, so every interpolated value passes through `esc()` and
`test_every_value_reaching_the_markup_is_escaped` renders a view whose strings are
hostile.

### Five modules, one boundary

| Module | Role | May touch the warehouse |
|---|---|---|
| `app/gateway.py` | application-tier facade; loads, renders, walks the trace | **yes** |
| `app/view_model.py` | plain strings and booleans — the boundary object | no |
| `app/blocks.py` | what to show, as data; numbers the sections | no |
| `app/document.py` | blocks → document markup; no arithmetic, everything escaped | no |
| `app/copy.py` | every client-facing sentence | no |
| `app/streamlit_app.py` | dispatcher: document runs, plus the two real widgets | no |

The UI receives a `ReportView` and has nothing else to work with. The tiers are
logical and co-located in one process (TDD 4.1, "in-process call"), so nothing
*physically* stops a UI module opening a cursor — what stops it is
`test_the_ui_module_cannot_reach_the_database`, which parses the module and
fails on a database import or a SQL keyword. Adding the coupling requires
deleting the test.

### Renders no figure it did not receive

Every number reaches the page as a string on the view model, formatted upstream
by the report's figure registry — which already refused to produce any figure
lacking provenance. `test_the_ui_displays_no_figure_the_view_model_did_not_carry`
walks every block, extracts every numeric literal and asserts it came from the
view model — and `test_no_figure_reaches_the_rendered_text_unaccounted_for` does
the same one layer down, on the text a browser would show, so a renderer that
reformatted a value cannot slip past a block-level check. That second test was
vacuous when first written: it passed the whole document as `_is_furniture`'s
context argument, which takes a *line*, so one furniture token anywhere excused
every number on the page. It now splits per element and
`test_that_rendered_text_check_catches_an_invented_figure` injects "73.2% by
2031" to prove it can fail. It reuses `report.provenance._is_furniture`, so "what counts as
document furniture" has one definition rather than two that can drift.

Backed by `test_no_block_performs_arithmetic`, an `ast` check that
`app/blocks.py` contains no `-`, `*`, `/`, `//`, `**` or `%`. A presentation
layer that could compute could produce a figure that is on no source, and the
figure test would have nothing to catch it with.

**Opening the page cannot change a number.** There is no path here that scores,
refits or calls a model — asserted for both the UI and the gateway.

### Proven to run, not just to be well-formed

Structural tests establish the boundary; they cannot establish that the blocks
reach real `st.*` calls without raising. Six tests use Streamlit's `AppTest`
harness to execute the actual script headlessly: **8 sections, 12 metrics,
3 tables, 2 warnings, 0 errors, no exception.** They skip with a stated reason
when no run has been scored.

### The perimeter, probed

`scripts/run_ui.py` binds `127.0.0.1:8501`. Verified live rather than assumed:
reachable on loopback, **connection refused on the machine's LAN address**. A
`--host` override exists and prints a loud warning, because the app serves a
customer-facing analysis with no authentication in front of it.

### Environment note

Streamlit 1.57 was installed but **could not import** — it requires
`starlette>=0.40` while `fastapi` pins `<0.39`. Pinned to **1.49.1**, the last
tornado-based release, which needs no starlette at all, so the conflict
disappears instead of moving. `langgraph` itself never depended on starlette
(only `langgraph-api`, which this project does not use). Its conservative
`pillow<12` cap was tested and does not bite: 1.49.1 runs on pillow 12.3.0,
which keeps an unrelated package of the user's working.

## Cohort calibration (W9 — complete)

```bash
python scripts/load_cohort.py --dry-run        # what would be loaded
python scripts/load_cohort.py                  # 12 occupations, 231 tasks
python scripts/score_cohort.py --classifier baseline          # free
python scripts/score_cohort.py --classifier model --persist   # the reference set
```

Calibration had never been reachable. The stated reason — one occupation has no
rank — was only half of it, and the other half was worse.

### Two problems, not one

1. **A percentile needs a distribution.** `percentile_within` refuses fewer
   than ten points. Scoring one more occupation would not have helped; the
   floor is 10.
2. **Ranks in different populations are not comparable.** Felten/Raj/Seamans
   place Financial Analysts at the 87th percentile *of 774 occupations*. Our
   index ranked among a handful we scored is a percentile of a different
   population. Comparing the two numbers would have looked like calibration and
   measured nothing.

### The fix: rank both series in the same cohort

Score N occupations, rank our index among those N, rank the published benchmark
among **those same N**, compare those. Both percentiles then describe one
reference set and the comparison is identified.

This is also the right comparison for two different estimands. AIOE is a
standardised index over work activities; ours is a task rubric with a tacitness
discount. Their *levels* were never commensurable, so a level comparison was
always going to be noise. Whether the two **orderings** agree is the meaningful
question, which is a rank question — so the cohort-wide statistic is Spearman's
rho and the per-occupation delta is its local view.

The cohort is every SOC 13-2\* occupation with both O*NET task statements and an
AIOE value: **12 occupations, 231 tasks**. Nothing was fetched — the O*NET dump
already in `data/docs` covers all 923 occupations and was already hashed. Only
13-2051 had ever been loaded.

One detail code per 6-digit SOC, because AIOE keys on 6 digits: loading both
13-2099.01 and .04 would put one benchmark observation into the distribution
twice.

### The defect the first cohort run exposed

The baseline cohort produced **delta 0.0 → `pass`**. It also produced **rank
correlation −0.4476**.

The target sat at rank 7 of 12 in *both* orderings by coincidence while the
orderings ran roughly opposite. A gate reading only the target's delta would
have certified a rubric that anti-correlates with the benchmark — which is the
exact failure mode of single-point calibration.

So the gate now requires **both** bars: delta within tolerance **and** rank
correlation at or above a floor. `MIN_RANK_CORRELATION = 0.30`, provisional
like the tolerance and labelled as such. `CALIBRATION_POLICY_VERSION` moved to
`provisional_v2_cohort`, because the criterion itself changed and a figure
calibrated under the old rule is not comparable to one under the new.

### The reference set is stored, not recomputed

Deriving the cohort costs one model call per task across every member. An
interactive run cannot pay that to answer a question about one occupation, so
`score.cohort_index` holds it, keyed on `(cohort, classifier, rubric_version)`
— a cohort scored by two classifiers is not one cohort, and the key makes the
mixture unrepresentable rather than merely discouraged.

`graph/runner.load_cohort_reference` reads it and injects it into `NodeDeps`.
The node ranks but never loads: `NodeDeps` promises a node holds no credential
and reaches data only through `tools`, and a node opening its own connection
would have quietly retracted that. A missing reference set degrades to "not
identifiable", never to a percentile over whatever rows happen to be present.

### Honest limits, both reported in the output

- **Granularity** is 100/N — 8.33 percentile points at N=12, against a ±15
  tolerance. Finer than the tolerance, but one position change moves the delta
  by more than half of it.
- **Cohort dependence.** A percentile within a chosen cohort is a statement
  about that cohort. This one is the finance family: the right frame for the
  customer question, the wrong frame for any claim about the whole economy.

## Mirror verification

```bash
python scripts/verify_sources.py --dry-run
python scripts/verify_sources.py
```

Two of the 29 artefacts were mirrors — the Felten/Raj/Seamans AIOE files, taken
from a third-party reproducibility repository rather than the authors'. Their
provenance note required a spot check before customer-facing use, and
`report.provenance` blocked `customer_deliverable` until one existed.

**Both are now verified, byte-identical to the authors' own distribution** at
`github.com/AIOE-Data/AIOE` — whose README carries the Felten/Raj/Seamans
citation and the authors' institutional contacts. That distinction is the
point: one GitHub URL is not automatically as good as another, and the reason
to trust this one is authorship, not the hostname.

This is what content addressing was for. A spot check of sampled values would
show they *look* right; re-fetching the publisher's file and comparing SHA-256
shows the bytes are **identical**, which is strictly stronger and needs no
judgement about which values to sample.

### Recorded as an event, not a flag

The result goes to `audit.source_verification`, never back onto
`ref.source_document`. Two reasons:

- That row is **immutable by design** — `db_fde_load` holds `DENY UPDATE` on
  it, because a snapshot whose digest can be edited is not a snapshot. Flipping
  `verified_against_publisher` would require mutating the very row the
  provenance chain rests on.
- A verification has a **time, a method, a counterpart URL and an outcome**,
  and it can be repeated. A publisher revision that breaks a previously passing
  check has to be able to sit in the record next to the check it invalidates. A
  boolean cannot hold that.

`db_fde_load` gets `INSERT, SELECT` and is denied `UPDATE`/`DELETE` — a
verification that can be edited afterwards proves nothing. `db_fde_score` gets
`SELECT` only, so the reporting side **cannot clear its own blocker**.

### What must not clear a mirror

The reader accepts a verification only when `publisher_sha256` equals the
artefact's own digest. Tested in both failing directions:

- a recorded **mismatch** does not clear it;
- a **passing** check recorded against a *different* digest does not clear it
  either — that verified some other version of the file.

A mismatch is never corrected by the script. It is recorded, and a human has to
explain the difference before delivery.

## Stack verification

```bash
python scripts/verify_stack.py                 # everything, including paid model calls
python scripts/verify_stack.py --no-models     # free: credentials, data APIs, warehouse
python scripts/verify_stack.py --layer data    # one layer
```

One command that exercises every external dependency: six credentials, four
government APIs, two model providers, the local warehouse, the tool surface,
and the whole pipeline from graph run through report to traceability walk.

Two deliberate choices:

- **It calls the project's own adapters, not raw HTTP.** A probe that bypasses
  the code under test confirms the vendor is up, not that this application can
  talk to it. Both of the bugs this exercise found were in the seam between the
  two, which a raw-HTTP probe would have missed entirely.
- **`SKIP` is not `PASS`.** A check that could not run is reported as such,
  with the reason, and the summary states that skips are not passes. Reporting
  an unrunnable check as green is how a broken dependency hides. Exit code is
  non-zero only on `FAIL`, so it is usable as a gate.

## Known data limitations

These constrain what the prototype may claim, and are repeated in the report:

1. **No securities breakout in the Census technology modules.** Both ABS
   modules publish at 2-digit NAICS only, so "finance" pools banking,
   insurance and securities. BEA *does* break out 523, so labour share and
   value added are available at securities level — adoption is not.
2. **No firm-size breakdown for finance** in the ABS technology module; only an
   all-firms figure. Size-conditioned claims about finance are unsupported.
3. **The adoption data predates LLMs.** 2018 and 2020 are the latest ABS
   technology vintages available here. They establish a pre-LLM baseline and a
   historical lag pattern; they say nothing directly about agent adoption.
4. **BTOS is not on the Census API.** The Business Trends and Outlook Survey
   carries current biweekly AI-use rates but is published as flat files only.
   Adding it is the highest-value next extension to the data layer.
5. **Compensation can exceed value added** in securities (>100% in some years)
   because value added is net of intermediate inputs and absorbs trading
   losses. Read the series as a trend, not a level.
6. **O*NET publishes no ratings for SOC 13-2051.** Its task list is
   analyst-written rather than survey-based, so there is no importance rating
   and no Core/Supplemental split. Neighbouring finance occupations do have
   ratings. This is an open decision for the rubric, not a defect.
