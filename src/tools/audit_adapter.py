"""The audit adapter: the only thing in the system that writes to the log.

Resolves the contradiction the original design left open. Every orchestration
node must emit an audit record, but ``USR_FDE_RO`` cannot write and
``USR_FDE_SCORE`` belongs to the scoring service. The architect's fix was a
fourth principal; the refinement adopted here is to hide it behind an adapter,
so **no orchestration node holds a write credential of any kind.** Nodes call
``emit``; the adapter owns the connection.

``tool_raw_output`` is stored unmodified. That is what makes a disputed figure
attributable: the exact rows the model saw are recoverable, so a wrong answer
can be pinned on the evidence or on the reasoning over it, rather than
argued about.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from warehouse.session import Principal, connect

LOG = logging.getLogger("tools.audit")

# The log column is NVARCHAR(MAX), but a single tool payload should not be
# unbounded. Truncation is recorded in the stored text so a reader knows the
# blob was clipped rather than that the tool returned little.
MAX_RAW_OUTPUT_CHARS = 200_000


@dataclass
class AuditEntry:
    """One decision-cycle record, matching ``audit.AgentAuditLog``."""

    run_id: str | None = None
    user_prompt: str | None = None
    node_invoked: str | None = None
    tool_invoked: str | None = None
    tool_raw_output: str | None = None
    llm_decision: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: int | None = None
    status: str | None = None


def _serialise(payload: Any) -> str | None:
    """Render a tool payload for storage, unmodified where possible."""
    if payload is None:
        return None
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    if len(text) > MAX_RAW_OUTPUT_CHARS:
        kept = text[:MAX_RAW_OUTPUT_CHARS]
        return (f"{kept}\n\n[TRUNCATED: {len(text)} chars original, "
                f"{MAX_RAW_OUTPUT_CHARS} retained]")
    return text


class AuditAdapter:
    """Append-only writer for the agent decision trail.

    Holds ``USR_FDE_AUDIT``, which is granted INSERT on
    ``audit.AgentAuditLog`` and nothing else — it cannot even read back what it
    writes. Until mixed-mode authentication is enabled the session layer falls
    back to the developer credential and logs a warning, so a run that believes
    it is sandboxed says otherwise loudly.
    """

    principal = Principal.AUDIT

    def __init__(self, run_id: str | None = None,
                 database: str | None = None, enabled: bool = True):
        self.run_id = run_id
        self._database = database
        self._enabled = enabled
        self._written = 0

    @property
    def entries_written(self) -> int:
        return self._written

    def emit(self, entry: AuditEntry) -> bool:
        """Append one entry. Returns False if auditing is disabled.

        A failure to write is logged at ERROR and re-raised: an unaudited run
        must not look like an audited one. The audit trail is the project's
        defensibility story, so losing a record silently is not an acceptable
        degradation.
        """
        if not self._enabled:
            return False

        with connect(self.principal, database=self._database,
                     autocommit=True) as conn:
            conn.cursor().execute("""
                INSERT INTO audit.AgentAuditLog
                    (run_id, user_prompt, node_invoked, tool_invoked,
                     tool_raw_output, llm_decision, provider, model,
                     prompt_version, input_tokens, output_tokens,
                     duration_ms, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                entry.run_id or self.run_id, entry.user_prompt,
                entry.node_invoked, entry.tool_invoked, entry.tool_raw_output,
                entry.llm_decision, entry.provider, entry.model,
                entry.prompt_version, entry.input_tokens, entry.output_tokens,
                entry.duration_ms, entry.status)

        self._written += 1
        LOG.info("run_id=%s node=%s tool=%s status=audited entries=%s",
                 entry.run_id or self.run_id, entry.node_invoked,
                 entry.tool_invoked, self._written)
        return True

    # -- convenience -------------------------------------------------------

    def tool_call(self, *, tool: str, node: str, payload: Any,
                  duration_ms: int | None = None,
                  status: str = "ok") -> bool:
        """Record a tool invocation with its raw output preserved."""
        return self.emit(AuditEntry(
            run_id=self.run_id, node_invoked=node, tool_invoked=tool,
            tool_raw_output=_serialise(payload),
            duration_ms=duration_ms, status=status))

    def model_call(self, *, node: str, provider: str, model: str,
                   prompt_version: str, decision: Any,
                   input_tokens: int | None = None,
                   output_tokens: int | None = None,
                   duration_ms: int | None = None,
                   status: str = "ok") -> bool:
        """Record a model invocation and what it decided."""
        return self.emit(AuditEntry(
            run_id=self.run_id, node_invoked=node, provider=provider,
            model=model, prompt_version=prompt_version,
            llm_decision=_serialise(decision), input_tokens=input_tokens,
            output_tokens=output_tokens, duration_ms=duration_ms, status=status))


class NullAuditAdapter(AuditAdapter):
    """No-op adapter for unit tests that are not exercising the audit trail.

    Deliberately explicit rather than a flag: a test that silences auditing
    should have to say so in its own setup.
    """

    def __init__(self, run_id: str | None = None):
        super().__init__(run_id=run_id, enabled=False)
        self.emitted: list[AuditEntry] = []

    def emit(self, entry: AuditEntry) -> bool:
        self.emitted.append(entry)
        self._written += 1
        return True
