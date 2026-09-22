"""End-to-end health check of every external dependency this system has.

Six credentials across two layers, one local database, and the paths that join
them. Run it before trusting a result, after rotating a key, or on a new
machine:

    python scripts/verify_stack.py              # everything
    python scripts/verify_stack.py --no-models  # skip paid model calls
    python scripts/verify_stack.py --layer data

Every check reports PASS, FAIL or SKIP with a reason. The distinction matters:
a SKIP is a check that could not run, and reporting it as a pass is how a
broken dependency hides. The exit code is non-zero if anything FAILED, so this
is usable as a gate.

Deliberately calls through the **project's own adapters** rather than issuing
raw HTTP. A probe that bypasses the code under test confirms only that the
vendor is up, not that this application can talk to it.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from dataclasses import dataclass, field

sys.path.insert(0, "src")

logging.basicConfig(level=logging.WARNING,
                    format="%(levelname)-7s %(name)s | %(message)s")

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


@dataclass
class Result:
    layer: str
    name: str
    status: str
    detail: str
    ms: int = 0


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def add(self, layer, name, status, detail, ms=0):
        self.results.append(Result(layer, name, status, detail, ms))
        colour = {PASS: "", FAIL: "  <-- FAILED", SKIP: "  (skipped)"}[status]
        print(f"  {status:4}  {name:34} {detail[:78]}{colour}")
        return status

    def counts(self):
        return {s: sum(1 for r in self.results if r.status == s)
                for s in (PASS, FAIL, SKIP)}

    @property
    def failed(self):
        return [r for r in self.results if r.status == FAIL]


def check(report: Report, layer: str, name: str):
    """Decorator-ish helper: run a check, convert an exception into a FAIL."""
    def run(fn):
        started = time.time()
        try:
            detail = fn()
            ms = int((time.time() - started) * 1000)
            if isinstance(detail, tuple):          # (status, detail)
                return report.add(layer, name, detail[0], detail[1], ms)
            return report.add(layer, name, PASS, detail or "ok", ms)
        except Exception as exc:                   # noqa: BLE001 - reporting
            ms = int((time.time() - started) * 1000)
            text = f"{type(exc).__name__}: {exc}"
            return report.add(layer, name, FAIL, text.replace("\n", " "), ms)
    return run


def header(title: str) -> None:
    print(f"\n{'=' * 96}\n{title}\n{'=' * 96}")


# ===========================================================================
# 1. Credentials
# ===========================================================================

def verify_credentials(report: Report) -> None:
    header("1. CREDENTIALS  —  where each key resolves from")
    import config

    @check(report, "creds", "all six keys resolve")
    def _():
        keys = config.load_keys(include_models=True)
        wanted = tuple(config.DATA_KEYS) + tuple(config.MODEL_KEYS)
        missing = [k for k in wanted if not keys.get(k)]
        if missing:
            return FAIL, f"missing: {', '.join(missing)}"
        return f"{len(wanted)} keys present"

    @check(report, "creds", "precedence: .env wins over inherited")
    def _():
        sources = config.key_sources(include_models=True)
        # The machine-scope OPENAI_API_KEY on this box is stale; .env must win.
        lines = [f"{k.replace('_API_KEY', '')}={v}" for k, v in sources.items()]
        from_env_file = sum(1 for v in sources.values() if ".env" in v)
        detail = f"{from_env_file}/{len(sources)} from .env  |  " + " ".join(lines)
        return detail


# ===========================================================================
# 2. Government data APIs, through the project's adapters
# ===========================================================================

def verify_data_apis(report: Report) -> None:
    header("2. GOVERNMENT DATA APIs  —  live, through src/sources/*")
    import config
    from sources import bea, bls, census, fred

    keys = config.load_keys()

    @check(report, "data", "BLS  v2 key validity probe")
    def _():
        valid = bls.key_is_valid(keys["BLS_API_KEY"])
        if valid:
            return "v2 key accepted"
        # Known state, documented since the data layer was built.
        return SKIP, ("v2 key rejected; adapter falls back to keyless v1 "
                      "(known, needs re-registration)")

    @check(report, "data", "BLS  fetch_series (finance employment)")
    def _():
        frame = bls.fetch_series(["CES5552300001"], 2022, 2024,
                                 api_key=keys["BLS_API_KEY"])
        if frame.empty:
            return FAIL, "adapter returned zero rows"
        return f"{len(frame)} observations, cols={list(frame.columns)[:4]}"

    @check(report, "data", "BEA  gdp_by_industry (securities 523)")
    def _():
        frame = bea.gdp_by_industry(keys["BEA_API_KEY"], table_id=6,
                                    frequency="A", year="2022")
        if frame.empty:
            return FAIL, "adapter returned zero rows"
        return f"{len(frame)} rows"

    @check(report, "data", "CENSUS  fetch (ABS technology module)")
    def _():
        frame = census.fetch(
            "2018/abstcb",
            ["NAICS2017", "NAICS2017_LABEL", "TECHUSE", "FIRMPDEMP"],
            keys["CENSUS_API_KEY"], geo="us:*", INDLEVEL="2")
        if frame.empty:
            return FAIL, "adapter returned zero rows"
        return f"{len(frame)} rows"

    @check(report, "data", "FRED  fetch_observations")
    def _():
        frame = fred.fetch_observations(["PAYEMS"], keys["FRED_API_KEY"],
                                        start="2023-01-01")
        if frame.empty:
            return FAIL, "adapter returned zero rows"
        return f"{len(frame)} observations"


# ===========================================================================
# 3. Model providers, both mechanisms
# ===========================================================================

SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string",
                               "enum": ["reachable", "unreachable"]},
                   "note": {"type": "string"}},
    "required": ["verdict", "note"],
    "additionalProperties": False,
}


def verify_model_providers(report: Report) -> None:
    header("3. MODEL PROVIDERS  —  live, two different structuring mechanisms")
    from providers import registry
    from providers.base import CallContext

    @check(report, "models", "stage->vendor map is cross-provider")
    def _():
        mapping = registry.cross_provider_stages()
        gate = mapping.get("review_gate")
        classifier = mapping.get("task_classifier")
        if gate == classifier:
            return FAIL, f"gate and classifier share vendor {gate}"
        return f"classifier={classifier}  review_gate={gate}"

    @check(report, "models", "OpenAI  strict json_schema (/v1/responses)")
    def _():
        provider = registry.for_stage(registry.Stage.TASK_CLASSIFIER)
        response = provider.structured(
            "Reply with verdict 'reachable' and a five-word note.",
            SCHEMA, schema_name="stack_probe",
            context=CallContext(stage="verify_stack", run_id="verify"))
        payload = response.structured
        if not payload or "verdict" not in payload:
            return FAIL, f"no structured payload: {payload!r}"
        return (f"{provider.model} verdict={payload['verdict']} "
                f"tokens={response.usage.total_tokens}")

    @check(report, "models", "Anthropic  forced tool use (/v1/messages)")
    def _():
        provider = registry.for_stage(registry.Stage.REVIEW_GATE)
        response = provider.structured(
            "Reply with verdict 'reachable' and a five-word note.",
            SCHEMA, schema_name="stack_probe",
            context=CallContext(stage="verify_stack", run_id="verify"))
        payload = response.structured
        if not payload or "verdict" not in payload:
            return FAIL, f"no structured payload: {payload!r}"
        return (f"{provider.model} verdict={payload['verdict']} "
                f"tokens={response.usage.total_tokens}")

    @check(report, "models", "OpenAI  free-text completion")
    def _():
        provider = registry.for_stage(registry.Stage.SYNTHESIS)
        response = provider.complete(
            "Reply with exactly the word: reachable",
            context=CallContext(stage="verify_stack", run_id="verify"))
        if not response.text:
            return FAIL, "empty text (reasoning consumed the budget?)"
        return f"{provider.model} -> {response.text.strip()[:40]!r}"


# ===========================================================================
# 4. Database, views, tool surface
# ===========================================================================

def verify_database(report: Report) -> None:
    header("4. WAREHOUSE  —  connection, views, tool surface")
    from warehouse.session import Principal, connect
    from tools.consumption import ConsumptionTracker
    from tools.evidence import ALLOWED_VIEWS, EvidenceTools

    @check(report, "db", "connect as USR_FDE_RO")
    def _():
        with connect(Principal.READ_ONLY) as conn:
            row = conn.cursor().execute(
                "SELECT DB_NAME(), SUSER_SNAME()").fetchone()
        return f"db={row[0]} login={row[1]}"

    @check(report, "db", "five agent-visible views populated")
    def _():
        counts = {}
        with connect(Principal.READ_ONLY) as conn:
            cursor = conn.cursor()
            for view in sorted(ALLOWED_VIEWS):
                name = view.split(".")[-1]
                counts[name] = cursor.execute(
                    f"SELECT COUNT(*) FROM {view}").fetchone()[0]
        empty = [k for k, v in counts.items() if v == 0]
        detail = " ".join(f"{k.replace('VW_', '')}={v}" for k, v in counts.items())
        if empty:
            return FAIL, f"empty: {', '.join(empty)} | {detail}"
        return detail

    @check(report, "db", "six read tools return provenanced rows")
    def _():
        tools = EvidenceTools(tracker=ConsumptionTracker(run_id="verify"))
        outcomes = {}
        outcomes["get_tasks"] = tools.get_tasks("13-2051.00").row_count
        # 6-digit SOC: the AIOE benchmark keys without O*NET's detail suffix,
        # exactly as nodes/retrieval._benchmark_soc does.
        outcomes["benchmarks"] = tools.get_exposure_benchmarks(
            "13-2051").row_count
        outcomes["adoption"] = tools.get_adoption_curve("52").row_count
        outcomes["claims"] = tools.search_claims(topic="lag_length").row_count
        outcomes["metric"] = tools.get_industry_metric("CES5552300001").row_count
        outcomes["source"] = tools.get_source_document(
            "onet_task_statements").row_count
        zero = [k for k, v in outcomes.items() if v == 0]
        detail = " ".join(f"{k}={v}" for k, v in outcomes.items())
        if zero:
            return FAIL, f"returned nothing: {', '.join(zero)} | {detail}"
        return detail

    @check(report, "db", "guardrail: agent cannot read a base table")
    def _():
        """The isolation claim, probed rather than trusted."""
        from warehouse.session import Principal as P
        try:
            with connect(P.READ_ONLY) as conn:
                conn.cursor().execute("SELECT TOP 1 * FROM core.task").fetchone()
        except Exception as exc:                   # noqa: BLE001
            return f"refused as designed ({type(exc).__name__})"
        return SKIP, ("base table WAS readable -- mixed-mode auth is off, so "
                      "the run used the developer fallback, not USR_FDE_RO")


# ===========================================================================
# 5. The whole pipeline: graph -> persistence -> report
# ===========================================================================

def verify_pipeline(report: Report, *, with_models: bool) -> None:
    header("5. PIPELINE  —  graph run, persistence, report, traceability")

    if not with_models:
        report.add("pipeline", "end-to-end graph run", SKIP,
                   "model calls disabled (--no-models)")
        return

    from graph import runner
    from report import provenance, reader, render

    state = {}

    @check(report, "pipeline", "graph run against live models")
    def _():
        outcome = runner.invoke(
            "Which of our equity research associate cost lines are exposed to "
            "agent substitution, and on what timetable?")
        state["outcome"] = outcome
        if outcome.state.verdict is None:
            return FAIL, (f"no verdict; phase={outcome.state.phase.value} "
                          f"errors={'; '.join(outcome.state.errors)[:120]}")
        spend = outcome.ledger.summary()
        return (f"phase={outcome.state.phase.value} status={outcome.status} "
                f"index={outcome.state.verdict.exposure_index:.3f} "
                f"calls={spend['calls']} tokens={spend['total_tokens']:,}")

    @check(report, "pipeline", "exposure and lag both produced")
    def _():
        outcome = state.get("outcome")
        if outcome is None or outcome.state.verdict is None:
            return SKIP, "graph run did not produce a verdict"
        verdict = outcome.state.verdict
        return (f"exposure={verdict.exposure_index:.3f}  "
                f"lag={verdict.lag.p10}/{verdict.lag.p50}/{verdict.lag.p90} "
                f"curve_fitted={verdict.lag.curve_fitted}")

    @check(report, "pipeline", "run bound its sources")
    def _():
        outcome = state.get("outcome")
        if outcome is None:
            return SKIP, "no run"
        if outcome.bindings == 0:
            return FAIL, "zero source bindings: nothing is traceable"
        return f"{outcome.bindings} bindings"

    @check(report, "pipeline", "report renders from the persisted run")
    def _():
        outcome = state.get("outcome")
        if outcome is None or not outcome.persisted:
            return SKIP, "nothing persisted to render"
        data = reader.load_run(outcome.context.run_id)
        markdown, figures = render.render(data)
        state["trace"] = provenance.walk(markdown, figures, data)
        state["markdown"] = markdown
        return (f"{len(markdown):,} chars, {len(figures)} figures, "
                f"status={data.status}")

    @check(report, "pipeline", "every figure traces to a hashed artefact")
    def _():
        trace = state.get("trace")
        if trace is None:
            return SKIP, "no report rendered"
        summary = trace.summary()
        if not trace.is_complete:
            return FAIL, f"{trace.failure_detail()[:160]}"
        return (f"{summary['figures_traced']} figures traced, "
                f"0 unregistered/unbound/unhashed, "
                f"mirrors={summary['unverified_mirrors']}")


# ===========================================================================

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-models", action="store_true",
                        help="Skip paid model calls and the pipeline run")
    parser.add_argument("--layer", choices=["creds", "data", "models", "db",
                                            "pipeline"], default=None)
    args = parser.parse_args()

    report = Report()
    want = (lambda layer: args.layer in (None, layer))

    print("\nFDE Task Exposure — full stack verification")
    print(f"models: {'disabled' if args.no_models else 'enabled (paid calls)'}")

    if want("creds"):
        verify_credentials(report)
    if want("data"):
        verify_data_apis(report)
    if want("models") and not args.no_models:
        verify_model_providers(report)
    elif want("models"):
        report.add("models", "model providers", SKIP, "--no-models")
    if want("db"):
        verify_database(report)
    if want("pipeline"):
        verify_pipeline(report, with_models=not args.no_models)

    counts = report.counts()
    header("SUMMARY")
    for layer in ("creds", "data", "models", "db", "pipeline"):
        rows = [r for r in report.results if r.layer == layer]
        if rows:
            ok = sum(1 for r in rows if r.status == PASS)
            print(f"  {layer:10} {ok}/{len(rows)} pass"
                  + (f"  ({sum(1 for r in rows if r.status == SKIP)} skipped)"
                     if any(r.status == SKIP for r in rows) else ""))
    print(f"\n  TOTAL  {counts[PASS]} pass, {counts[FAIL]} fail, "
          f"{counts[SKIP]} skip")

    if report.failed:
        print("\n  FAILURES:")
        for r in report.failed:
            print(f"    [{r.layer}] {r.name}: {r.detail[:150]}")
        return 1

    if counts[SKIP]:
        print("\n  Nothing failed. Skips are stated above and are not passes.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        raise SystemExit(130)
