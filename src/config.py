"""Configuration and credential loading.

The project's .env uses a YAML-ish ``KEY: 'value'`` form rather than strict
dotenv ``KEY=value``, and is CRLF-terminated without a trailing newline.  The
loader here tolerates both separators so the file can stay as the user wrote it.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_INTERIM = PROJECT_ROOT / "data" / "interim"

# Data-source credentials: required for ingestion.
DATA_KEYS = ("BEA_API_KEY", "CENSUS_API_KEY", "FRED_API_KEY", "BLS_API_KEY")

# Model credentials: required for the orchestration tier, not for ingestion.
# Both providers are used deliberately (TDD 2): the Review Gate must not be the
# same model that produced the work it is grading.
MODEL_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")

REQUIRED_KEYS = DATA_KEYS


class ConfigError(RuntimeError):
    """Raised when credentials are missing or unreadable."""


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file accepting either ``KEY=value`` or ``KEY: value``."""
    if not path.exists():
        raise ConfigError(f"No .env file at {path}")

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for sep in ("=", ":"):
            if sep in line:
                key, _, value = line.partition(sep)
                values[key.strip()] = value.strip().strip("'\"").strip()
                break
    return values


def load_keys(include_models: bool = False) -> dict[str, str]:
    """Return the API keys, preferring real environment variables.

    ``include_models`` additionally requires the model-provider credentials, so
    an ingestion run does not fail for want of a key it never uses.

    Fails fast and names every key that is missing, rather than failing later
    inside an HTTP call with an opaque provider error.
    """
    wanted = tuple(REQUIRED_KEYS) + (MODEL_KEYS if include_models else ())
    file_values = _parse_env_file(ENV_PATH)
    keys = {k: os.environ.get(k) or file_values.get(k, "") for k in wanted}

    missing = [k for k, v in keys.items() if not v]
    if missing:
        raise ConfigError(
            f"Missing API key(s): {', '.join(missing)}. "
            f"Add them to {ENV_PATH} as KEY: 'value' or export them."
        )
    return keys


def ensure_dirs() -> None:
    """Create the data directories the fetchers write into."""
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    DATA_INTERIM.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Model configuration
#
# gpt-6-astra is a reasoning model. Two constraints were established by direct
# probing of the live API rather than assumed:
#
#   1. Function tools are NOT supported on /v1/chat/completions for this
#      model. The API directs callers to /v1/responses, and reasoning_effort
#      cannot be set to 'none' to work around it.
#   2. Structured outputs (strict json_schema) work on BOTH endpoints.
#
# The project therefore standardises on /v1/responses for every model call, so
# there is one code path rather than two with different capabilities.
# --------------------------------------------------------------------------

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Overridable by environment variable, per the charter: model names must not be
# hardcoded deeply in business logic.
#
# The split is intentional. Intent/Scope and the Review Gate run on Anthropic so
# the gate grading the classifier's work is a different model from the one that
# produced it -- a mild independence property that a single-provider setup loses.
MODEL_CLASSIFIER = os.environ.get("MODEL_CLASSIFIER", "gpt-6-astra")
MODEL_WRITER = os.environ.get("MODEL_WRITER", "gpt-6-astra")
MODEL_ORCHESTRATOR = os.environ.get("MODEL_ORCHESTRATOR", "claude-opus-5")
MODEL_REVIEW_GATE = os.environ.get("MODEL_REVIEW_GATE", "claude-opus-5")

# Valid for gpt-6-astra: low | medium | high | xhigh. Default is medium.
REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "medium")
