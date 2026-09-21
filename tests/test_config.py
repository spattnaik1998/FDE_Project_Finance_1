"""Credential resolution: most specific source wins.

The precedence rule is deliberately *not* plain environment-beats-file. A
machine-scope environment variable is system-wide configuration; a project's
own ``.env`` is narrower and more intentional, so the project wins. A variable
someone exported for *this process* still wins over both, because they meant it.

This was not a theoretical preference. A stale machine-level `OPENAI_API_KEY`
shadowed a valid `.env` entry and surfaced as an opaque provider 401, with no
fix available short of Administrator rights. Under this rule the project works
without elevation and says which source it chose.
"""

from __future__ import annotations

import pytest

import config


@pytest.fixture
def file_values():
    return {"OPENAI_API_KEY": "sk-from-dotenv", "BEA_API_KEY": "bea-from-dotenv"}


# --- The precedence ladder ---------------------------------------------------

def test_dotenv_wins_over_an_inherited_system_variable(monkeypatch, file_values):
    """The case that actually bit: a stale machine-scope key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stale-machine-value")
    monkeypatch.setattr(config, "persisted_env_value",
                        lambda name: "sk-stale-machine-value")

    value, source = config.resolve_key("OPENAI_API_KEY", file_values)
    assert value == "sk-from-dotenv"
    assert source == config.ENV_PATH.name


def test_explicitly_exported_variable_wins_over_dotenv(monkeypatch, file_values):
    """Someone exported it for this run, so they meant it."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-exported-for-this-process")
    # Differs from what is persisted, so it was set deliberately.
    monkeypatch.setattr(config, "persisted_env_value",
                        lambda name: "sk-stale-machine-value")

    value, source = config.resolve_key("OPENAI_API_KEY", file_values)
    assert value == "sk-exported-for-this-process"
    assert source == "process environment"


def test_inherited_variable_is_used_when_there_is_no_dotenv_entry(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "from-machine")
    monkeypatch.setattr(config, "persisted_env_value", lambda name: "from-machine")

    value, source = config.resolve_key("SOME_KEY", {})
    assert value == "from-machine"
    assert source == "inherited system environment"


def test_dotenv_is_used_when_nothing_is_in_the_environment(monkeypatch, file_values):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    value, source = config.resolve_key("OPENAI_API_KEY", file_values)
    assert value == "sk-from-dotenv"
    assert source == config.ENV_PATH.name


def test_absent_everywhere_resolves_to_empty(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    monkeypatch.setattr(config, "persisted_env_value", lambda name: None)
    assert config.resolve_key("NOPE_KEY", {}) == ("", "unset")


def test_no_persisted_value_means_the_environment_was_explicit(monkeypatch,
                                                               file_values):
    """Off Windows, or for a var not in the registry, env is taken as deliberate."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-exported")
    monkeypatch.setattr(config, "persisted_env_value", lambda name: None)
    assert config.resolve_key("OPENAI_API_KEY", file_values)[1] == "process environment"


# --- Diagnostics -------------------------------------------------------------

def test_the_override_is_logged_not_silent(monkeypatch, file_values, caplog):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stale")
    monkeypatch.setattr(config, "persisted_env_value", lambda name: "sk-stale")
    with caplog.at_level("INFO"):
        config.resolve_key("OPENAI_API_KEY", file_values)
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "dotenv_overrides_inherited_env" in messages
    assert "broader in scope" in messages


def test_relying_on_an_inherited_variable_warns(monkeypatch, caplog):
    """No .env entry means a stale system value will be used; say so."""
    monkeypatch.setenv("SOME_KEY", "from-machine")
    monkeypatch.setattr(config, "persisted_env_value", lambda name: "from-machine")
    with caplog.at_level("WARNING"):
        config.resolve_key("SOME_KEY", {})
    assert any("using_inherited_system_env" in r.getMessage()
               for r in caplog.records)


def test_key_sources_reports_every_credential():
    sources = config.key_sources(include_models=True)
    assert set(sources) == set(config.REQUIRED_KEYS) | set(config.MODEL_KEYS)
    assert all(v for v in sources.values())


# --- Registry read -----------------------------------------------------------

def test_persisted_lookup_needs_no_elevation():
    """Reading user/machine scope is unprivileged; only writing needs admin."""
    assert config.persisted_env_value("PATH")


def test_persisted_lookup_returns_none_for_an_absent_variable():
    assert config.persisted_env_value("FDE_DEFINITELY_NOT_SET_ANYWHERE") is None


# --- Fail-fast behaviour -----------------------------------------------------

def test_missing_credentials_are_named(monkeypatch):
    monkeypatch.setattr(config, "_parse_env_file", lambda path: {})
    monkeypatch.setattr(config, "persisted_env_value", lambda name: None)
    for key in config.REQUIRED_KEYS:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(config.ConfigError) as exc:
        config.load_keys()
    for key in config.REQUIRED_KEYS:
        assert key in str(exc.value)


def test_model_keys_are_not_required_for_ingestion(monkeypatch):
    """An ingestion run must not fail for want of a key it never uses."""
    monkeypatch.setattr(config, "_parse_env_file",
                        lambda path: {k: "x" for k in config.REQUIRED_KEYS})
    monkeypatch.setattr(config, "persisted_env_value", lambda name: None)
    for key in config.MODEL_KEYS:
        monkeypatch.delenv(key, raising=False)

    assert set(config.load_keys()) == set(config.REQUIRED_KEYS)
    with pytest.raises(config.ConfigError):
        config.load_keys(include_models=True)


# --- The .env parser ---------------------------------------------------------

@pytest.mark.parametrize("line,expected", [
    ("KEY = 'value'", "value"),
    ("KEY='value'", "value"),
    ("KEY=value", "value"),
    ("KEY: 'value'", "value"),
    ("KEY:value", "value"),
    ('KEY = "value"', "value"),
])
def test_parser_accepts_every_form_the_file_has_used(tmp_path, line, expected):
    """The file has been hand-edited into several shapes across the project."""
    path = tmp_path / ".env"
    path.write_text(f"{line}\n", encoding="utf-8")
    assert config._parse_env_file(path)["KEY"] == expected


def test_parser_skips_comments_and_blanks(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# a comment\n\nKEY = 'v'\n", encoding="utf-8")
    assert config._parse_env_file(path) == {"KEY": "v"}


def test_parser_tolerates_crlf_and_no_trailing_newline(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"A = '1'\r\nB = '2'")
    assert config._parse_env_file(path) == {"A": "1", "B": "2"}


def test_parser_raises_on_a_missing_file(tmp_path):
    with pytest.raises(config.ConfigError, match="No .env file"):
        config._parse_env_file(tmp_path / "absent")
