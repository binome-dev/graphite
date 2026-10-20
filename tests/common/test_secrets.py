"""Tests for what holds a secret, by its name, and what refers to one instead
(grafi.common.secrets)."""

from typing import Any
from typing import Dict

import pytest

from grafi.common.secrets import env_reference
from grafi.common.secrets import env_variables_in
from grafi.common.secrets import expand_env
from grafi.common.secrets import held_secret
from grafi.common.secrets import is_env_reference
from grafi.common.secrets import is_secret_name
from tests.common.manifest_fixtures import HELD_SECRETS
from tests.common.manifest_fixtures import UNHELD_SETTINGS

# --------------------------------------------------------------------------- #
# Names that say they hold a secret
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    [
        "api_key",
        "OPENAI_API_KEY",
        "apikey",
        "X-Api-Key",
        "secret",
        "client_secret",
        "secret_key",
        "private_key",
        "access_key",
        "password",
        "passwd",
        "credentials",
        "auth",
        "Authorization",
        "Cookie",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "bearer_token",
        "session_token",
        "api_token",
        "github_token",
        "GITHUB_TOKEN",
        "hf_token",
        "clientSecret",
        "api_keys",
        "passwords",
        "client_secrets",
        "PGPASSWORD",
        "OpenAIApiKey",
        "dbPassword",
        "accessToken",
        "apiSecret",
        "apiKey",
        "x-auth-token",
        "Proxy-Secret",
        "slack-bot-token",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ],
)
def test_names_that_say_they_hold_a_secret(name: str) -> None:
    assert is_secret_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "max_tokens",
        "maxTokens",
        "cache_key",
        "tokens",
        "token_count",
        "author",
        "keyword",
        "secretary",
        "url",
        "env",
        "headers",
        "",
        # A tokenizer's special tokens.
        "eos_token",
        "bos_token",
        "pad_token",
        "unk_token",
        "sep_token",
        "cls_token",
        "mask_token",
        "PAD_TOKEN",
        "padToken",
    ],
)
def test_names_that_do_not_say_they_hold_a_secret(name: str) -> None:
    assert not is_secret_name(name)


# --------------------------------------------------------------------------- #
# References to environment variables
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "${GITHUB_TOKEN}",
        "  ${GITHUB_TOKEN} ",
        "Bearer ${GITHUB_TOKEN}",
        "bearer ${GITHUB_TOKEN}",
        "Basic ${CREDENTIALS}",
        "Token ${API_TOKEN}",
        "ApiKey ${ES_API_KEY}",
        "Api-Key ${ES_API_KEY}",
        "SSWS ${OKTA_TOKEN}",
        "oauth",  # A way to authenticate, as MCP's "auth": "oauth".
    ],
)
def test_text_that_only_refers_to_a_variable(text: str) -> None:
    assert is_env_reference(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "sk-literal",
        "$GITHUB_TOKEN",
        "${1BAD}",
        "${}",
        "Bearer sk ${API_TOKEN}",
        "${OPENAI_API_KEY}-suffix",
        "Bearer ${A} ${B}",
        "Unknown ${API_TOKEN}",
        "OAuth",  # Only MCP's own spelling names a way to authenticate.
    ],
)
def test_text_that_holds_more_than_a_reference(text: str) -> None:
    assert not is_env_reference(text)


@pytest.mark.parametrize(
    "value, var",
    [
        ({"env": "GITHUB_TOKEN"}, "GITHUB_TOKEN"),
        ({"env": "_x1"}, "_x1"),
        ({"env": "sk-FAKE-1"}, None),  # No variable's name: a value.
        ({"env": "1BAD"}, None),
        ({"env": ""}, None),
        ({"env": None}, None),
        ({"env": "GITHUB_TOKEN", "default": "x"}, None),  # Only the one key.
        ({"environment": "GITHUB_TOKEN"}, None),
        ("${GITHUB_TOKEN}", None),  # Text, not the field's form.
        ("GITHUB_TOKEN", None),
        (None, None),
        (["env", "GITHUB_TOKEN"], None),
    ],
)
def test_the_variable_a_secret_field_refers_to(value: Any, var: Any) -> None:
    assert env_reference(value) == var


@pytest.mark.parametrize(
    "text, variables",
    [
        ("", []),
        ("plain", []),
        ("$MCP_TOKEN", []),
        ("${1BAD} ${}", []),
        ("${MCP_HOST}", ["MCP_HOST"]),
        ("https://${MCP_HOST}/mcp?token=${MCP_TOKEN}", ["MCP_HOST", "MCP_TOKEN"]),
        ("${A}${A}", ["A", "A"]),
        ('{"env": {"KEY": "${_K1}"}}', ["_K1"]),
    ],
)
def test_the_variables_text_refers_to(text: str, variables: Any) -> None:
    assert env_variables_in(text) == variables


def test_expand_env_replaces_each_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_HOST", "mcp.example.com")
    monkeypatch.setenv("MCP_TOKEN", "t0ken")

    assert expand_env("https://${MCP_HOST}/mcp") == "https://mcp.example.com/mcp"
    assert expand_env("Bearer ${MCP_TOKEN}") == "Bearer t0ken"
    assert expand_env("${MCP_HOST}:${MCP_TOKEN}") == "mcp.example.com:t0ken"
    assert expand_env("${MCP_TOKEN}${MCP_TOKEN}") == "t0kent0ken"


@pytest.mark.parametrize("text", ["$MCP_TOKEN", "costs $5", "${1BAD}", "${}", "plain"])
def test_expand_env_leaves_other_text_alone(
    monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    monkeypatch.setenv("MCP_TOKEN", "t0ken")

    assert expand_env(text) == text


def test_expand_env_raises_for_an_unset_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_HOST", "mcp.example.com")
    monkeypatch.delenv("MCP_MISSING_TOKEN", raising=False)
    match = "The environment variable MCP_MISSING_TOKEN is referred to, but not set."

    with pytest.raises(ValueError, match=match):
        expand_env("https://${MCP_HOST}/mcp?token=${MCP_MISSING_TOKEN}")


def test_expand_env_expands_an_empty_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_EMPTY", "")

    assert expand_env("a${MCP_EMPTY}b") == "ab"


# --------------------------------------------------------------------------- #
# held_secret: the name a value holds a secret at, if any
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name, value",
    [
        ("api_key", "sk-literal"),
        ("Authorization", "Bearer sk-literal"),
        ("Authorization", "Bearer sk ${API_TOKEN}"),  # More than a reference.
        ("api_key", "${OPENAI_API_KEY}-suffix"),
        ("GITHUB_TOKEN", "ghp_literal"),
        ("clientSecret", "cs"),
        ("auth", "literal-token"),
        ("api_key", {"env": "sk-FAKE-1"}),  # No variable's name: a value.
        ("api_key", {"class": "sk-FAKE-1"}),  # Not a component's class.
        ("api_keys", {"openai": "sk-1"}),  # All within it is under its name.
        ("credentials", {"key": "sk-1"}),
        ("api_key", [["openai", "sk-pair"]]),
        ("auth", {"oauth": {"client_secret": "literal"}}),
        ("token", ["t0ken"]),
    ],
)
def test_a_value_held_under_a_secrets_name(name: str, value: Any) -> None:
    assert held_secret(name, value) == name


@pytest.mark.parametrize(
    "name, value",
    [
        ("api_key", ""),
        ("api_key", None),
        ("secret", 0),
        ("access_token", True),
        ("api_key", "${OPENAI_API_KEY}"),
        ("Authorization", "Bearer ${GITHUB_TOKEN}"),
        ("Authorization", "Basic ${CREDENTIALS}"),
        ("auth", "oauth"),
        ("api_key", {"env": "OPENAI_API_KEY"}),  # A secret field's reference.
        ("credentials", {"env": "GOOGLE_CREDENTIALS"}),
        ("max_tokens", "100"),
        ("eos_token", "</s>"),
        ("tokens", ["a", "b"]),
        ("api_keys", {}),
        ("api_key", []),
        ("api_keys", {"openai": "${OPENAI_API_KEY}"}),
    ],
)
def test_a_value_holding_no_secret_under_a_secrets_name(name: str, value: Any) -> None:
    assert held_secret(name, value) is None


@pytest.mark.parametrize("field, value, held", HELD_SECRETS)
def test_a_secret_held_at_any_depth_is_named(
    field: str, value: Dict[str, Any], held: str
) -> None:
    """The name reported is the outermost secret's: the key whose value holds
    it, or a dict's or list's whole name when all within it is a secret."""
    assert held_secret(field, value) == held


@pytest.mark.parametrize("params", UNHELD_SETTINGS)
def test_settings_without_a_secret_value_hold_none(params: Dict[str, Any]) -> None:
    assert held_secret("params", params) is None


def test_a_components_class_is_skipped_in_a_dict() -> None:
    """A dict naming a component's class, an import path, is a component: its
    "class" is no secret, but its other fields are checked."""
    assert held_secret("tool", {"class": "my_app:Tool", "model": "m"}) is None
    assert held_secret("tool", {"class": "my_app:Tool", "api_key": "sk"}) == "api_key"
    # A "class" that is not an import path is a value like any other.
    assert held_secret("api_key", {"class": "sk-FAKE-1"}) == "api_key"


@pytest.mark.parametrize(
    "pairs, held",
    [
        ([["Accept", "text/plain"], ["Authorization", "Bearer sk-1"]], "Authorization"),
        ([["Authorization", "Bearer ${API_TOKEN}"], ["Accept", "*/*"]], None),
        ([["X-Api-Key", ""]], None),
        ([["Accept", "text/plain"], ["not", "a", "pair"]], None),
        ([("Cookie", "session=abc")], "Cookie"),  # A tuple is a pair too.
    ],
)
def test_lists_of_name_value_pairs_are_read_as_headers(pairs: Any, held: Any) -> None:
    assert held_secret("headers", pairs) == held


# A URL holding a secret is reported under its own name: its password, or a
# query parameter named like a secret, that is not a reference to a variable.
@pytest.mark.parametrize(
    "url",
    [
        "postgresql://app:pw@db.example.com/app",
        "https://bot:pw@example.com/mcp",
        "https://example.com/mcp?api_key=sk-1&page=2",
        "https://example.com/mcp?access_token=t0ken",
        "https://example.com/mcp?page=2&client_secret=cs",
        "redis://:pw@cache.example.com:6379/0",
        "https://[bad-ipv6/mcp?api_key=sk-1",  # Unreadable, so refused.
    ],
)
def test_a_url_holding_a_secret(url: str) -> None:
    assert held_secret("url", url) == "url"
    assert held_secret("proxy", url) == "proxy"  # Under its own name.
    assert held_secret("settings", {"db": {"url": url}}) == "url"
    assert held_secret("mirrors", [url]) == "mirrors"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://app:${DB_PASSWORD}@db.example.com/app",
        "https://bot:${MCP_PASSWORD}@example.com/mcp",
        "https://bot@example.com/mcp",  # A user, no password.
        "https://example.com/mcp?token=${MCP_TOKEN}",
        "https://example.com/mcp?page=2&q=x",
        "https://example.com/mcp?api_key=",  # Empty.
        "https://example.com/@me",
        "not a url, with api_key=sk-1 in it",  # No scheme: text, not a URL.
    ],
)
def test_a_url_holding_no_secret(url: str) -> None:
    assert held_secret("url", url) is None
    assert held_secret("settings", {"db": {"url": url}}) is None
