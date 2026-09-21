"""Model-facing tool specifications.

The same six tools, described as JSON schemas so a provider can call them. Both
adapters take this shape — the OpenAI adapter passes it to ``/v1/responses``
and the Anthropic adapter converts the ``parameters`` block into an
``input_schema`` — so a tool is declared once and works on either.

Descriptions are written for the model, and they carry the guardrails rather
than leaving them to a system prompt. A tool that says *suppressed cells are
never zero* in its own description is harder to misuse than one whose caveats
live three thousand tokens away.
"""

from __future__ import annotations

from typing import Any

from tools.evidence import EvidenceTools


def _spec(name: str, description: str, properties: dict,
          required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOL_SPECS: list[dict] = [
    _spec(
        "get_tasks",
        "Return the published task statements for one occupation, with the "
        "weighting convention in force. Every row carries Source_Doc_ID. "
        "Fails rather than substituting a neighbouring occupation if the one "
        "requested is not published.",
        {"soc_code": {"type": "string",
                      "description": "O*NET-SOC code, e.g. '13-2051.00'"}},
        ["soc_code"],
    ),
    _spec(
        "get_exposure_benchmarks",
        "Return published occupation-level exposure indices. Each value comes "
        "with a Scale_Note stating what the number means and its range: these "
        "are standardised relative indices, not probabilities or percentages, "
        "and are meaningless without it.",
        {"soc_code": {"type": "string", "description": "SOC code to look up"},
         "measure": {"type": "string",
                     "description": "Optional measure filter, e.g. "
                                    "'AIOE_language_modeling'"}},
        ["soc_code"],
    ),
    _spec(
        "get_adoption_curve",
        "Return the survey adoption trajectory for one NAICS sector. "
        "Suppressed survey cells have Value NULL and Is_Suppressed set — they "
        "are missing information, never zero, and must not be treated as a "
        "decline. Note the sector granularity: NAICS 52 pools banking and "
        "insurance with securities.",
        {"sector_code": {"type": "string",
                         "description": "2-digit NAICS sector, e.g. '52'"},
         "question_code": {"type": "string",
                           "description": "Survey question, default '7' "
                                          "(current AI use)"},
         "answer_label": {"type": "string",
                          "description": "Answer option, default 'Yes'"},
         "include_suppressed": {"type": "boolean",
                                "description": "Include suppressed cells to see "
                                               "where data is missing"}},
        ["sector_code"],
    ),
    _spec(
        "search_claims",
        "Retrieve verbatim claims from the source literature by topic or free "
        "text. Every claim carries its exact quote, page number and publisher. "
        "You may cite ONLY what this tool returns: do not recall or reconstruct "
        "a source. Claims flagged Is_Mirror come from a third-party copy rather "
        "than the publisher and block a customer-deliverable run.",
        {"topic": {"type": "string",
                   "description": "Topic key, e.g. 'lag_length', "
                                  "'not_prediction', 'j_curve_definition'"},
         "text": {"type": "string",
                  "description": "Free-text phrase to match within quotes"},
         "limit": {"type": "integer", "description": "Maximum claims to return"}},
        [],
    ),
    _spec(
        "get_industry_metric",
        "Return one economic time series (BEA, BLS, Census or FRED), "
        "optionally narrowed by industry code and period.",
        {"series_id": {"type": "string",
                       "description": "Series identifier, e.g. 'OPHNFB'"},
         "industry_code": {"type": "string",
                           "description": "Optional industry dimension, e.g. '523'"},
         "start": {"type": "string", "description": "ISO date lower bound"},
         "end": {"type": "string", "description": "ISO date upper bound"}},
        ["series_id"],
    ),
    _spec(
        "get_source_document",
        "Resolve a Source_Doc_ID to its title, publisher, SHA-256 digest and "
        "mirror status, so a citation can be checked. Reference metadata only: "
        "it carries no evidence.",
        {"doc_id": {"type": "string", "description": "A Source_Doc_ID"}},
        ["doc_id"],
    ),
]


def openai_tools() -> list[dict]:
    """Specs in the shape ``/v1/responses`` expects."""
    return [{"type": "function", **spec} for spec in TOOL_SPECS]


def anthropic_tools() -> list[dict]:
    """Specs in the shape the Messages API expects.

    Anthropic calls the schema ``input_schema``; the content is identical.
    """
    return [{"name": spec["name"], "description": spec["description"],
             "input_schema": spec["parameters"]} for spec in TOOL_SPECS]


def dispatch(tools: EvidenceTools, name: str, arguments: dict) -> Any:
    """Route a model's tool call to the implementation.

    Unknown names raise rather than being ignored: a model calling a tool that
    does not exist is a prompt or schema problem, and swallowing it would let
    the run continue on missing evidence.
    """
    handlers = {
        "get_tasks": tools.get_tasks,
        "get_exposure_benchmarks": tools.get_exposure_benchmarks,
        "get_adoption_curve": tools.get_adoption_curve,
        "search_claims": tools.search_claims,
        "get_industry_metric": tools.get_industry_metric,
        "get_source_document": tools.get_source_document,
    }
    if name not in handlers:
        raise KeyError(
            f"Unknown tool {name!r}. The published surface is: "
            f"{', '.join(sorted(handlers))}")
    return handlers[name](**arguments)


def spec_names() -> list[str]:
    return [spec["name"] for spec in TOOL_SPECS]
