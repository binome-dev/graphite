"""An MCP tool's configuration, ``{"mcpServers": {name: connection}}``, as the
MCP tools hold it, save it and connect with it.

A manifest never holds a secret, so a setting of a server that holds one -- a
header, an environment variable, ``auth``, a URL parameter -- refers to the
environment variable holding it, as ``"Bearer ${GITHUB_TOKEN}"``, which
:func:`with_env` expands when connecting. A secret in a setting not named like
one, such as a command's argument, is not recognized: write it as ``${VAR}``
too. See :mod:`grafi.common.secrets`.
"""

import json
from typing import Annotated
from typing import Any
from typing import Dict
from typing import Mapping

from pydantic import BeforeValidator
from pydantic import PlainSerializer
from pydantic import ValidationInfo

from grafi.common.manifest import ManifestError
from grafi.common.manifest import ManifestPolicy
from grafi.common.manifest import save_refused
from grafi.common.secrets import env_variables_in
from grafi.common.secrets import expand_env
from grafi.common.secrets import held_secret

__all__ = ["MCPConfig", "check_mcp_secrets", "with_env"]


def with_env(config: Any) -> Any:
    """An MCP configuration with each ``${VAR}`` in its strings replaced by the
    value of the environment variable ``VAR``, as the client is given it.

    Raises:
        ValueError: If a variable referred to is not set.
    """
    if isinstance(config, str):
        return expand_env(config)
    if isinstance(config, Mapping):
        return {key: with_env(value) for key, value in config.items()}
    if isinstance(config, list):
        return [with_env(value) for value in config]
    return config


def check_mcp_secrets(config: Mapping[str, Any]) -> None:
    """Raise :class:`ManifestError` for a secret an MCP configuration holds as
    a value, naming the server; see this module."""
    servers = config.get("mcpServers") or {}
    for server, connection in servers.items() if isinstance(servers, Mapping) else ():
        held = held_secret("", connection)
        if held is not None:
            raise save_refused(
                ManifestError(
                    f"The MCP server {server!r} has {held!r} set to a value, and "
                    "a manifest never holds a secret: refer to an environment "
                    'variable holding it, as "${VAR}", which is expanded when '
                    "connecting."
                )
            )


def _save_config(config: Dict[str, Any]) -> Dict[str, Any]:
    check_mcp_secrets(config)
    return config


def _load_config(config: Any, info: ValidationInfo) -> Any:
    """A configuration from a manifest reads only the variables it may; that
    it holds no secret, the component loading it checks."""
    policy = ManifestPolicy.of(info.context)
    if policy is not None and isinstance(config, Mapping):
        for var in env_variables_in(json.dumps(config)):  # A manifest is JSON.
            policy.check_env(var)
    return config


# An MCP configuration, saved as it is (see check_mcp_secrets()), and connected
# with with_env().
MCPConfig = Annotated[
    Dict[str, Any],
    PlainSerializer(_save_config, when_used="json"),
    BeforeValidator(_load_config),
]
