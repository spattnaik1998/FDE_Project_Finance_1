"""Configuration and credential loading.

The project's .env uses a YAML-ish ``KEY: 'value'`` form rather than strict
dotenv ``KEY=value``, and is CRLF-terminated without a trailing newline.  The
loader here tolerates both separators so the file can stay as the user wrote it.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

LOG = logging.getLogger("config")

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


def persisted_env_value(name: str) -> str | None:
    """The value of an env var as *persisted* in Windows user/machine scope.

    Used to tell an inherited system-wide variable apart from one a caller
    exported deliberately for this process. Reading the registry needs no
    elevation; only writing does.

    Returns ``None`` off Windows, where the distinction does not exist and the
    ordinary precedence applies.
    """
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None

    scopes = (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    )
    for root, path in scopes:
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, name)
                if value:
                    return str(value)
        except (FileNotFoundError, OSError):
            continue
    return None


def resolve_key(name: str, file_values: dict[str, str]) -> tuple[str, str]:
    """Resolve one credential, most-specific source first.

    Precedence, deliberately not plain environment-over-file:

    1. An environment variable **explicitly set for this process** — someone
       exported it for this run, so they meant it.
    2. The project's ``.env``.
    3. An **inherited** user- or machine-scope environment variable.

    The distinction in (1) versus (3) matters. A machine-scope variable is
    system-wide configuration; a project's own ``.env`` is narrower and more
    intentional, so the project should win. Plain
    environment-beats-file precedence let a stale machine-level key shadow a
    valid ``.env`` entry and surface as an opaque provider 401 — with no way
    to fix it short of Administrator rights.

    Returns ``(value, source)`` so the caller can log which source won.
    """
    env_value = os.environ.get(name)
    file_value = file_values.get(name)

    if env_value:
        persisted = persisted_env_value(name)
        inherited = persisted is not None and env_value == persisted

        if not inherited:
            return env_value, "process environment"
        if file_value:
            LOG.info(
                "key=%s status=dotenv_overrides_inherited_env -- using %s "
                "(...%s) in preference to the inherited system variable "
                "(...%s), which is broader in scope",
                name, ENV_PATH.name, file_value[-4:], env_value[-4:])
            return file_value, ENV_PATH.name
        LOG.warning(
            "key=%s status=using_inherited_system_env -- no %s entry, so the "
            "system-wide variable is used. If it is stale, provider calls will "
            "fail with an auth error.", name, ENV_PATH.name)
        return env_value, "inherited system environment"

    if file_value:
        return file_value, ENV_PATH.name
    return "", "unset"


def load_keys(include_models: bool = False) -> dict[str, str]:
    """Return the API keys, resolving each from its most specific source.

    ``include_models`` additionally requires the model-provider credentials, so
    an ingestion run does not fail for want of a key it never uses.

    Fails fast and names every key that is missing, rather than failing later
    inside an HTTP call with an opaque provider error.
    """
    wanted = tuple(REQUIRED_KEYS) + (MODEL_KEYS if include_models else ())
    file_values = _parse_env_file(ENV_PATH)

    keys: dict[str, str] = {}
    for name in wanted:
        value, _source = resolve_key(name, file_values)
        keys[name] = value

    missing = [k for k, v in keys.items() if not v]
    if missing:
        raise ConfigError(
            f"Missing API key(s): {', '.join(missing)}. "
            f"Add them to {ENV_PATH} as KEY = 'value' or export them."
        )
    return keys


def key_sources(include_models: bool = False) -> dict[str, str]:
    """Which source each credential resolved from. For diagnostics."""
    wanted = tuple(REQUIRED_KEYS) + (MODEL_KEYS if include_models else ())
    file_values = _parse_env_file(ENV_PATH)
    return {name: resolve_key(name, file_values)[1] for name in wanted}


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

# How many task classifications may be in flight at once.
#
# The classifier issues one call per task and they are independent, so running
# them serially was pure latency -- 26 tasks x ~7s. Six is deliberately modest:
# a 231-call cohort build exhausted the provider quota earlier in this project,
# and the adapters' 429 backoff recovers from a brush with the limit far better
# than from a stampede into it. Raise it only with the rate limit in view.
CLASSIFIER_CONCURRENCY = int(os.environ.get("CLASSIFIER_CONCURRENCY", "6"))


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
#
# At least one provider echoes the submitted credential back inside its own
# error message. BLS does:
#
#     "The key:<the key you just sent> provided by the User is invalid"
#
# and the adapter logged that message verbatim, so a freshly rotated key was
# printed to the console the first time it was used. Found the hard way, during
# a rotation.
#
# The defence is keyed on the *actual* configured values rather than on shape
# alone: a heuristic that only matches "looks like a key" will miss a
# credential whose format it does not know, and every provider invents its own.
# Shape patterns are kept as a second line for values not in our own config
# (someone else's key quoted back at us, a token in a payload).

_SHAPE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),          # OpenAI-style
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{12,}"),      # Anthropic-style
    re.compile(r"\b[0-9a-f]{32}\b"),                # BLS/Census-style hex
    re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
               r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b"),  # GUID-style (BEA)
)

MASK = "<redacted>"


def redact(text: object) -> str:
    """Mask any configured credential, or credential-shaped token, in ``text``.

    Use this on anything that originated with a provider before logging it or
    putting it in an exception. A provider's error text is not ours and may
    contain whatever the provider chose to include -- including what we sent.

    Redacts the longest values first, so a key that contains another shorter
    value cannot be partially unmasked.
    """
    rendered = str(text)
    if not rendered:
        return rendered

    try:
        known = [v for v in load_keys(include_models=True).values() if v]
    except Exception:                               # noqa: BLE001 - never block
        known = []
    for value in sorted(known, key=len, reverse=True):
        if len(value) >= 8:                         # avoid masking trivia
            rendered = rendered.replace(value, MASK)

    for pattern in _SHAPE_PATTERNS:
        rendered = pattern.sub(MASK, rendered)
    return rendered
