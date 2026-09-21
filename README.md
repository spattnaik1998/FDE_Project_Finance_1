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

Four keys in `.env` (gitignored), read by `src/config.py`, which tolerates both
`KEY=value` and the `KEY: 'value'` form the file currently uses.

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

### Environment prerequisites not yet met

1. **Mixed-mode authentication is disabled.** The four SQL logins cannot be
   created until it is enabled, which needs a registry change and a SQL Server
   service restart affecting the instance's other 26 databases.
2. **Full-Text Search is not installed.** Needed for `VW_CLAIM_EVIDENCE`
   retrieval in P3, not for P1 or P2.

Because of (1) the loader currently runs under the developer's trusted
connection rather than `USR_FDE_LOAD`. `session.py` logs this at WARNING on
every run, and `test_integration.py` asserts the isolation is *not* in force
rather than passing silently — the security model is built and constrained, but
untested at runtime until mixed mode is enabled.

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

### Cost accounting withholds rather than guesses

Token counts are facts the API reports and are always recorded. **Cost is
reported only when a price is configured** via `PRICE_<MODEL>_INPUT` /
`_OUTPUT`. `gpt-6-astra` postdates this project's reference material, so its
price is not known here; the ledger returns `cost_usd: None` with
`cost_status: "unpriced_models: gpt-6-astra"` rather than a total that silently
omits half the calls.

### Retry

Retries 408/409/425/429 and 5xx with exponential backoff plus jitter; raises
immediately on any other 4xx, because a 400 will be 400 again. `run_id` and
`stage` travel on every call through `CallContext` and appear in every log line.

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
