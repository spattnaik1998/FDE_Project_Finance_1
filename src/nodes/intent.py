"""Intent & Scope: resolve a request to a scope, or refuse.

Runs on Anthropic. Its one hard behaviour is a refusal: an occupation we do not
publish must produce an out-of-scope halt, never a neighbouring occupation
quietly substituted. A customer asking about a role we have not scored and
getting a confident answer about a different role is the worst failure this
system could have — worse than no answer, because it looks like one.

The candidate list comes from the warehouse, not the model's memory, so the
model chooses among real options rather than proposing a SOC code that may not
exist.
"""

from __future__ import annotations

import logging

from nodes import prompts
from nodes.state import NodeDeps, Phase, RunState, Scope
from providers.base import CallContext, ProviderError
from providers.registry import Stage
from warehouse.session import Principal, connect

LOG = logging.getLogger("nodes.intent")

NODE = "1. Intent & Scope"


def available_scopes(database: str | None = None) -> tuple[list[dict], list[dict]]:
    """Occupations and sectors that are actually published.

    Read directly rather than through the tool surface: this is the scope
    *catalogue*, not evidence, and no run has been bound yet.
    """
    with connect(Principal.READ_ONLY, database=database, autocommit=True) as conn:
        cursor = conn.cursor()
        occupations = [
            {"soc_code": r[0], "title": r[1], "tasks": r[2]}
            for r in cursor.execute("""
                SELECT SOC_Code, MIN(Occupation), COUNT(*)
                FROM dbo.VW_ROLE_TASKS GROUP BY SOC_Code ORDER BY SOC_Code
            """).fetchall()]
        sectors = [
            {"sector_code": r[0], "label": r[1]}
            for r in cursor.execute("""
                SELECT DISTINCT Sector_Code, Sector_Label
                FROM dbo.VW_ADOPTION_CURVE
                WHERE Sector_Code IS NOT NULL ORDER BY Sector_Code
            """).fetchall()]
    return occupations, sectors


def run(state: RunState, deps: NodeDeps,
        database: str | None = None) -> RunState:
    """Resolve ``state.request`` into a :class:`Scope`, or halt out of scope."""
    occupations, sectors = available_scopes(database)

    if not occupations:
        return state.fail(Phase.FAILED,
                          "No occupations are published; the warehouse is empty.")

    occ_lines = "\n".join(
        f"  {o['soc_code']}  {o['title']}  ({o['tasks']} tasks)" for o in occupations)
    sector_lines = "\n".join(
        f"  {s['sector_code']}  {s['label']}" for s in sectors) or "  (none)"

    provider = deps.provider(Stage.INTENT_SCOPE)
    try:
        response = provider.structured(
            prompts.INTENT_USER.format(request=state.request,
                                       occupations=occ_lines,
                                       sectors=sector_lines),
            prompts.INTENT_SCHEMA,
            schema_name="scope_resolution",
            system=prompts.INTENT_SYSTEM,
            max_tokens=1200,
            context=CallContext(run_id=state.run_id, stage=Stage.INTENT_SCOPE.value,
                                prompt_version=deps.prompt_version))
    except ProviderError as exc:
        return state.fail(Phase.FAILED, f"Intent resolution failed: {exc}")

    deps.ledger.record(response, stage=Stage.INTENT_SCOPE.value,
                       prompt_version=deps.prompt_version)
    deps.audit.model_call(node=NODE, provider=response.provider,
                          model=response.model,
                          prompt_version=deps.prompt_version,
                          decision=response.structured,
                          input_tokens=response.usage.input_tokens,
                          output_tokens=response.usage.output_tokens,
                          duration_ms=response.duration_ms)

    answer = response.structured or {}

    if not answer.get("resolved"):
        reason = answer.get("rationale") or "the request did not resolve to a published scope"
        LOG.warning("node=intent status=out_of_scope run_id=%s reason=%s",
                    state.run_id, reason)
        return state.fail(Phase.OUT_OF_SCOPE,
                          f"Request is out of scope: {reason}")

    soc = (answer.get("soc_code") or "").strip()
    sector = (answer.get("naics_sector") or "").strip()

    # The model must choose from the list, not invent. Verified rather than
    # trusted: a hallucinated SOC code would sail through the schema, which
    # only constrains the type.
    known_socs = {o["soc_code"] for o in occupations}
    known_sectors = {s["sector_code"] for s in sectors}

    if soc not in known_socs:
        return state.fail(
            Phase.OUT_OF_SCOPE,
            f"Resolved SOC {soc!r} is not published. Available: "
            f"{', '.join(sorted(known_socs))}. Refusing rather than "
            f"substituting a neighbouring occupation.")

    if sector and sector not in known_sectors:
        LOG.warning("node=intent status=sector_unavailable sector=%s", sector)
        state.unresolved.append(
            f"Sector {sector!r} has no published adoption evidence; the lag "
            f"path will have nothing to read.")

    title = next((o["title"] for o in occupations if o["soc_code"] == soc), "")
    state.scope = Scope(soc_code=soc, naics_sector=sector,
                        geography=answer.get("geography") or "US",
                        occupation_title=title,
                        rationale=answer.get("rationale", ""))
    state.phase = Phase.SCOPED

    LOG.info("node=intent status=scoped run_id=%s soc=%s sector=%s",
             state.run_id, soc, sector)
    return state
