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

## Database (P1 — complete)

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

### Environment prerequisites not yet met

1. **Mixed-mode authentication is disabled.** The four SQL logins cannot be
   created until it is enabled, which needs a registry change and a SQL Server
   service restart affecting the instance's other 26 databases.
2. **Full-Text Search is not installed.** Needed for `VW_CLAIM_EVIDENCE`
   retrieval in P3, not for P1 or P2.

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
