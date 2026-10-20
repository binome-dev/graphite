"""Tests for an MCP tool's configuration (grafi.tools.mcp_config): saved with
its secrets as references to environment variables, never as values, and
expanded when connecting."""

import copy
from typing import Any
from typing import Dict

import pytest
from pydantic import BaseModel
from pydantic import Field
from pydantic_core import PydanticSerializationError

from grafi.common.manifest import ManifestError
from grafi.tools.function_calls.impl.mcp_tool import MCPTool
from grafi.tools.mcp_config import MCPConfig
from grafi.tools.mcp_config import check_mcp_secrets
from grafi.tools.mcp_config import with_env


class Server(BaseModel):
    mcp_config: MCPConfig = Field(default_factory=dict)


def _config(headers: Any = None, env: Any = None) -> Dict[str, Any]:
    connection: Dict[str, Any] = {"url": "https://example.com/mcp", "transport": "http"}
    if headers is not None:
        connection["headers"] = headers
    if env is not None:
        connection["env"] = env
    return {"mcpServers": {"github": connection}}


def _mcp_manifest(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "apiVersion": "grafi/v2",
        "kind": "Tool",
        "spec": {
            "class": "grafi.tools.function_calls.impl.mcp_tool:MCPTool",
            "mcp_config": config,
        },
    }


# --------------------------------------------------------------------------- #
# with_env: ${VAR} references expanded when connecting
# --------------------------------------------------------------------------- #


def test_with_env_expands_references_everywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_HOST", "mcp.example.com")
    monkeypatch.setenv("MCP_TOKEN", "t0ken")
    config = {
        "mcpServers": {
            "github": {
                "url": "https://${MCP_HOST}/mcp",
                "headers": {"Authorization": "Bearer ${MCP_TOKEN}"},
                "args": ["--host=${MCP_HOST}", "--token=${MCP_TOKEN}", 3],
                "env": {"PAIR": "${MCP_HOST}:${MCP_TOKEN}"},
                "timeout": 30.0,
                "enabled": True,
                "cwd": None,
            }
        }
    }
    saved = copy.deepcopy(config)

    expanded = with_env(config)

    assert expanded == {
        "mcpServers": {
            "github": {
                "url": "https://mcp.example.com/mcp",
                "headers": {"Authorization": "Bearer t0ken"},
                "args": ["--host=mcp.example.com", "--token=t0ken", 3],
                "env": {"PAIR": "mcp.example.com:t0ken"},
                "timeout": 30.0,
                "enabled": True,
                "cwd": None,
            }
        }
    }
    assert config == saved  # The saved configuration keeps its references.


@pytest.mark.parametrize("text", ["$MCP_TOKEN", "costs $5", "${1BAD}", "${}", "plain"])
def test_with_env_leaves_other_text_alone(
    monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    monkeypatch.setenv("MCP_TOKEN", "t0ken")

    assert with_env({"value": text}) == {"value": text}
    assert with_env(text) == text


@pytest.mark.parametrize("value", [3, 30.0, True, None, ()])
def test_with_env_leaves_values_that_are_not_text_alone(value: Any) -> None:
    assert with_env(value) == value


def test_with_env_raises_for_an_unset_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_HOST", "mcp.example.com")
    monkeypatch.delenv("MCP_MISSING_TOKEN", raising=False)
    config = {"headers": [{"Authorization": "Bearer ${MCP_MISSING_TOKEN}"}]}
    match = "The environment variable MCP_MISSING_TOKEN is referred to, but not set."

    with pytest.raises(ValueError, match=match):
        with_env(config)


# --------------------------------------------------------------------------- #
# A manifest reads only the variables it is allowed
# --------------------------------------------------------------------------- #


def test_a_manifest_reads_only_the_variables_it_is_allowed() -> None:
    """A connection loaded from a manifest cannot read a variable the
    application did not name, so it cannot send it to a server of its
    choosing; a connection written in code reads any."""
    leak = "https://example.com/collect?leak=${AWS_SECRET_ACCESS_KEY}"
    config = {"mcpServers": {"s": {"transport": "http", "url": leak}}}

    with pytest.raises(ManifestError, match="AWS_SECRET_ACCESS_KEY"):
        MCPTool.from_manifest(_mcp_manifest(config))

    tool = MCPTool.from_manifest(_mcp_manifest(config), env=["AWS_SECRET_ACCESS_KEY"])
    assert tool.mcp_config == config
    assert MCPTool(mcp_config=config).mcp_config == config


@pytest.mark.parametrize(
    "connection",
    [
        {"command": "server", "args": ["--key=${MCP_TEST_KEY}"]},
        {"url": "https://example.com", "headers": {"X-Key": "${MCP_TEST_KEY}"}},
        {"command": "server", "env": {"KEY": "${MCP_TEST_KEY}"}},
        {"url": "https://example.com", "session_kwargs": {"a": ["${MCP_TEST_KEY}"]}},
    ],
    ids=["args", "headers", "env", "nested"],
)
def test_every_reference_in_a_manifest_must_be_allowed(
    connection: Dict[str, Any],
) -> None:
    config = {"mcpServers": {"s": {"transport": "stdio", **connection}}}

    with pytest.raises(ManifestError, match=r"MCP_TEST_KEY.*env=\['MCP_TEST_KEY'\]"):
        MCPTool.from_manifest(_mcp_manifest(config))
    tool = MCPTool.from_manifest(_mcp_manifest(config), env=["MCP_TEST_KEY"])
    assert tool.mcp_config == config  # Kept as a reference, expanded on connecting.


# --------------------------------------------------------------------------- #
# check_mcp_secrets: a secret is saved as a reference, never as a value
# --------------------------------------------------------------------------- #


def _refused(name: str) -> str:
    return f"The MCP server 'github' has '{name}' set to a value"


@pytest.mark.parametrize(
    "name", ["Authorization", "X-Api-Key", "Cookie", "x-auth-token", "Proxy-Secret"]
)
def test_secret_header_with_a_value_raises(name: str) -> None:
    with pytest.raises(ManifestError, match=_refused(name)):
        check_mcp_secrets(_config(headers={name: "Bearer ghp_literal"}))


@pytest.mark.parametrize(
    "name",
    [
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "DB_PASSWORD",
        "CLIENT_SECRET",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "slack-bot-token",
    ],
)
def test_secret_environment_variable_with_a_value_raises(name: str) -> None:
    """The variable's name is reported: "env" is no secret's name."""
    with pytest.raises(ManifestError, match=_refused(name)):
        check_mcp_secrets(_config(env={name: "literal-secret"}))


# The name reported is the outermost secret's (see grafi.common.secrets): the
# header's or variable's, 'auth' for all within it, and 'url' for a URL's
# password or secret parameter.
@pytest.mark.parametrize(
    "connection, name",
    [
        ({"auth": "literal-token"}, "auth"),
        ({"auth": {"oauth": {"client_secret": "literal"}}}, "auth"),
        ({"session_kwargs": {"auth": {"password": "pw"}}}, "auth"),
        ({"headers": [{"Authorization": "Bearer x"}]}, "Authorization"),
        ({"command": "srv", "args": [{"password": "hunter2"}]}, "password"),
        ({"url": "https://example.com/mcp?api_key=sk-1&page=2"}, "url"),
        ({"url": "https://example.com/mcp?access_token=t0ken"}, "url"),
        ({"url": "https://bot:pw@example.com/mcp"}, "url"),
        ({"headers": {"Authorization": "Bearer sk ${GITHUB_TOKEN}"}}, "Authorization"),
    ],
    ids=[
        "auth",
        "auth nested",
        "nested",
        "list",
        "list of settings",
        "url api_key",
        "url access_token",
        "url password",
        "more than a reference",
    ],
)
def test_secret_anywhere_in_a_connection_raises(
    connection: Dict[str, Any], name: str
) -> None:
    config = {"mcpServers": {"github": {"transport": "http", **connection}}}

    with pytest.raises(ManifestError, match=_refused(name)) as raised:
        check_mcp_secrets(config)
    assert '"${VAR}"' in str(raised.value)  # It says how to refer to it.


def test_secrets_given_as_references_are_saved() -> None:
    config = _config(
        headers={"Authorization": "Bearer ${GITHUB_TOKEN}", "X-Api-Key": "${API_KEY}"},
        env={"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
    )
    config["mcpServers"]["github"]["url"] = "https://example.com/?token=${MCP_TOKEN}"
    saved = copy.deepcopy(config)

    assert check_mcp_secrets(config) is None
    assert config == saved


@pytest.mark.parametrize(
    "connection",
    [
        {"auth": "oauth"},  # A way to authenticate, not a secret.
        {"headers": {"Authorization": "Basic ${MCP_CREDENTIALS}"}},
        {"headers": {"Authorization": "Token ${MCP_TOKEN}"}},
        {"url": "https://bot:${MCP_PASSWORD}@example.com/mcp"},
        {"url": "https://bot@example.com/mcp"},
    ],
)
def test_connections_referring_to_their_secrets_are_saved(
    connection: Dict[str, Any],
) -> None:
    config = {"mcpServers": {"github": {"transport": "http", **connection}}}

    assert check_mcp_secrets(config) is None


def test_values_that_are_not_secrets_are_saved() -> None:
    config = _config(
        headers={"Content-Type": "application/json", "User-Agent": "grafi"},
        env={"PATH": "/usr/bin", "LOG_LEVEL": "debug", "MAX_TOKENS": "8080"},
    )
    config["mcpServers"]["github"]["url"] = "https://example.com/mcp?page=2&q=x"

    assert check_mcp_secrets(config) is None


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"mcpServers": {}},
        {"mcpServers": None},
        {"mcpServers": ["not", "a", "mapping"]},
        _config(),
        _config(headers={}, env={}),
        {"mcpServers": {"local": {"command": "python", "env": None}}},
        _config(headers={"Authorization": None}),  # Not a string: nothing saved.
    ],
)
def test_configurations_without_secrets_are_saved(config: Dict[str, Any]) -> None:
    assert check_mcp_secrets(config) is None
    assert Server(mcp_config=config).model_dump(mode="json") == {"mcp_config": config}


# --------------------------------------------------------------------------- #
# MCPConfig: the field, as a tool holds it
# --------------------------------------------------------------------------- #


def test_mcp_config_field_saves_references_unexpanded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    config = _config(headers={"Authorization": "Bearer ${GITHUB_TOKEN}"})
    server = Server(mcp_config=config)

    assert server.model_dump() == {"mcp_config": config}
    assert server.model_dump(mode="json") == {"mcp_config": config}
    assert "t0ken" not in server.model_dump_json()


def test_mcp_config_field_with_a_secret_value_cannot_be_saved_as_json() -> None:
    config = _config(headers={"Authorization": "Bearer ghp_x"})
    server = Server(mcp_config=config)

    with pytest.raises(PydanticSerializationError, match=_refused("Authorization")):
        server.model_dump(mode="json")
    with pytest.raises(PydanticSerializationError, match=_refused("Authorization")):
        server.model_dump_json()
    assert server.model_dump() == {"mcp_config": config}  # Its values, in process.


def test_mcp_tool_with_a_secret_value_cannot_be_saved() -> None:
    tool = MCPTool(mcp_config=_config(env={"GITHUB_TOKEN": "ghp_literal"}))

    with pytest.raises(ManifestError, match=_refused("GITHUB_TOKEN")):
        tool.to_manifest()


@pytest.mark.parametrize(
    "connection, match",
    [
        (
            {"env": {"GITHUB_TOKEN": "ghp_literal"}},
            "MCPTool.mcp_config holds a secret, at 'GITHUB_TOKEN'",
        ),
        (
            {"url": "https://bot:pw@example.com/mcp"},
            "MCPTool.mcp_config holds a secret, at 'url'",
        ),
        (
            {"url": "https://example.com/mcp?api_key=sk-1"},
            "MCPTool.mcp_config holds a secret, at 'url'",
        ),
    ],
    ids=["env", "url password", "url parameter"],
)
def test_a_manifest_never_gives_an_mcp_secret_as_a_value(
    connection: Dict[str, Any], match: str
) -> None:
    config = {"mcpServers": {"github": {"transport": "http", **connection}}}

    with pytest.raises(ManifestError, match=match):
        MCPTool.from_manifest(_mcp_manifest(config))
    assert MCPTool(mcp_config=config).mcp_config == config  # In code, a value.
