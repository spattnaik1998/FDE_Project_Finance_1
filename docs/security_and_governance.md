# Security and Governance

What is enforced, where it is enforced, and what is not yet proven. Written for
a reviewer who will not take an assertion on trust — which is the audience this
project is built for.

The distinction that matters throughout: **a control is enforced where it is
refused, not where it is documented.** Every claim below says which of the two
it is.

---

## 1. Trust boundaries

```
  Browser (127.0.0.1:8501)          no credential, no SQL, no arithmetic
        │  in-process call
  Presentation tier                 receives a ReportView of plain strings
        │
  Application tier                  holds the credentials; loads, renders, ranks
        │  ODBC, loopback only
  SQL Server (127.0.0.1:1433)       four principals, deny-by-default
        │
  Model providers (HTTPS egress)    two vendors, disjoint stages
```

Three things cross a boundary and are therefore checked at it:

| Crossing | Control | Enforced by |
|---|---|---|
| UI → data | UI cannot import a DB library or contain SQL | `ast` parse test; fails the build |
| Agent → warehouse | Five views only; base tables denied | SQL `DENY` + `ALLOWED_VIEWS` whitelist + `ast` test |
| Model → customer figure | Every number traced to a SHA-256 | figure registry refuses to render an unprovenanced value |

---

## 2. The four principals

None holds a server role. None is a member of `db_datareader`,
`db_datawriter` or `db_owner`. Each has `CONNECT` plus membership in exactly one
database role.

| Principal | Holds | Explicitly denied |
|---|---|---|
| `USR_FDE_RO` | `SELECT` on the five `VW_*` views | every base table, all DDL |
| `USR_FDE_LOAD` | `INSERT`/`SELECT` on `ref`, `core`; `INSERT` on verification | `UPDATE`/`DELETE` on facts; `ref.source_document` immutable; all of `AgentAuditLog` |
| `USR_FDE_SCORE` | `INSERT` on `score.*`, `UPDATE` on `score.run` only | `UPDATE` on any persisted score; `DELETE` on `score`; `SELECT` on `AgentAuditLog` |
| `USR_FDE_AUDIT` | `INSERT` on `AgentAuditLog` only | `SELECT` on what it writes; all of `ref`, `core`, `score` |

Two consequences worth stating because they are the point of the split:

- **No orchestration node holds a write credential.** Nodes emit audit records
  through an adapter that holds `USR_FDE_AUDIT`; the agent can request a score
  but cannot write one.
- **The reporting side cannot clear its own blocker.** `db_fde_score` has
  `SELECT` but not `INSERT` on `audit.source_verification`, so the component
  that decides whether a document is deliverable cannot manufacture the
  evidence that makes it so.

> **Not yet proven.** Until mixed-mode auth is enabled these grants sit on
> **roles with no logins in them**, so every process connects as the developer.
> `session.py` logs a WARNING on every such run, `verify_stack.py` reports the
> base-table guardrail as **`SKIP — cannot verify`** rather than as passing, and
> 30 tests skip with that reason. This is the single largest open gap.

---

## 3. What is logged

Five append-only records. None holds a secret.

| Table | Records | Append-only by |
|---|---|---|
| `audit.AgentAuditLog` | every node and tool call, with `tool_raw_output` unmodified | `DENY` + `INSTEAD OF` trigger that rejects UPDATE/DELETE including for sysadmin |
| `audit.run_source_binding` | which source versions a run **consumed** | PK + `DENY UPDATE/DELETE` to the writer |
| `audit.source_verification` | mirror checks: time, method, counterpart URL, outcome | `DENY UPDATE/DELETE`; writer is ingestion, reader is scoring |
| `audit.security_event` | privilege changes: auth mode, logins, ACL restriction | denied to **all four** application principals |
| `audit.quality_assertion` | data-quality assertions per load | `INSERT` only |

`tool_raw_output` is stored unmodified on purpose: when a customer disputes a
figure, the question is whether the *evidence* or the *reasoning over it* was
wrong, and that is unanswerable if the tool output was normalised on the way in.

`audit.security_event` carries a `CHECK` that rejects `PASSWORD =`, `PASSWORD=`
and `sk-` in its detail column. A cheap guard against the realistic failure —
an operator pasting a connection string into an audit note — not a scrubber.

---

## 4. Secrets

| Control | State |
|---|---|
| `.env` gitignored, never committed | **in force** (verified against full git history) |
| `.env` ACL restricted to owner + SYSTEM + Administrators | **`scripts/harden_secrets.ps1`** — run it |
| SQL passwords generated, never echoed, never in the repo | in force |
| Passwords passed to `sqlcmd` via environment, not command line | in force |
| Credential precedence: process env → `.env` → inherited env | in force, 22 tests |
| **API keys rotated** | **NOT DONE — see below** |

**Gitignoring a secrets file and restricting who can open it are different
controls for different threats.** Only the first was in place: `.env` inherited
`BUILTIN\Users FullControl` from the enclosing folder, so every local account
could read all six API keys. `harden_secrets.ps1` fixes that, and
`enable_sql_auth.ps1` now **refuses to run** while a broad Allow entry remains —
appending database passwords to a world-readable file would convert a
rotatable problem into durable credential exposure.

A command line is not a secret: any process that can enumerate processes can
read another's full command line. The original script passed all four passwords
as `sqlcmd -v` arguments; they now go through the environment and are cleared in
a `finally` block.

> **Outstanding and not fixable by a script.** Six API keys have been readable
> by every local account on a machine whose project repository is public. They
> should be **rotated before any client session**, independently of the ACL fix.
> Nothing in the code changes — only the values in `.env`.

---

## 5. Network perimeter

- SQL Server binds `127.0.0.1:1433`; no remote listener.
- Streamlit binds `127.0.0.1:8501`. **Verified, not assumed**: reachable on
  loopback, connection *refused* on the machine's LAN address. This is a
  standing check in `verify_stack.py --layer ui`.
- The app has **no authentication**. On loopback that is acceptable; the
  `--host` override exists and prints a loud warning, because a customer-facing
  analysis served on `0.0.0.0` is published to the local network.
- Egress: two model vendors and five public data publishers over HTTPS. No
  inbound path.

---

## 6. Governance of the analysis itself

Security controls stop the wrong person reading a number. These stop the
*system* asserting one it cannot support.

- **Provenance is a precondition.** `report/figures.py` refuses to render a
  figure that cannot name a source document. An unprovenanced number is
  unrenderable, not merely flagged.
- **Unrepresentable rather than discouraged.** FK to `ref.source_document`
  makes an unprovenanced fact impossible to insert; `CHECK (LEN(caveats) > 0)`
  makes a caveat-free verdict impossible to persist.
- **Versioned criteria.** `rubric_version` and
  `calibration_policy_version` are recorded per run. The calibration criterion
  changed when cohort calibration arrived, so the version moved to
  `provisional_v2_cohort`; figures calibrated under the two rules are not
  comparable and the record says which applies.
- **Both bootstraps are labelled as such.** The ±15-point tolerance and the
  0.30 rank-correlation floor are engineering bootstraps, not validated
  criteria, and are named `provisional` in the data.
- **Three-state gate.** Calibration *disagreement* and calibration *failure*
  are different outcomes. A gate that collapsed them would either suppress a
  finding or become decorative.
- **Mirror provenance.** A mirrored source blocks `customer_deliverable` until
  a recorded digest match against the publisher exists. A recorded *mismatch*
  does not clear it, and neither does a passing check against a different
  digest — that verified another version of the file.

---

## 7. Runbook

Order matters. Step 1 must precede step 2.

```powershell
# 1. Restrict the secrets file.  Non-elevated.  Dry run first if you like.
cd C:\Users\91838\Downloads\code_test
powershell -File scripts\harden_secrets.ps1 -WhatIf
powershell -File scripts\harden_secrets.ps1

# 2. Enable mixed-mode auth and create the four principals.  ELEVATED.
#    Restarts MSSQLSERVER: drops connections to all 31 databases on the instance.
powershell -File scripts\enable_sql_auth.ps1

# 3. Verify.  Non-elevated.
python -m pytest tests/test_privileges.py -v
python scripts/verify_database.py
python scripts/verify_stack.py
```

No `-ExecutionPolicy Bypass`: `CurrentUser` is already `RemoteSigned`, which
permits a local unsigned script, and neither file carries a mark-of-the-web.
Bypass would weaken the policy for the whole process and buy nothing.

**Reversal.** `icacls .env /inheritance:e` for step 1. For step 2, set
`LoginMode` back to `1`, restart the service, and `DROP LOGIN` each
`USR_FDE_*`; the project falls back to the developer credential and keeps
working.

---

## 8. Open items, honestly stated

| Item | Impact | Who can close it |
|---|---|---|
| **Mixed-mode auth off** | Whole RBAC model unproven at runtime; 30 tests skip | you, elevated — step 2 above |
| **API keys not rotated** | Six keys exposed to local accounts; public repo | you, at the providers |
| `.env` ACL | Fixed by step 1, not yet run | you — step 1 above |
| BLS v2 key rejected | Falls back to keyless v1, narrower window; logged | free re-registration |
| Full-Text not installed | `search_claims` falls back to `LIKE` and says so | SQL Server install media |
| No rate-limit budgeting | A batch job and an interactive run starve each other | engineering, not yet built |

Nothing in this list is hidden from the running system: each one either logs a
warning, reports a `SKIP` with its reason, or surfaces in the report's own
limitations section. **A gap that the system reports is a known risk; a gap it
conceals is a defect.**
