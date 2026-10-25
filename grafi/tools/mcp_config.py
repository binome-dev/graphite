"""An MCP tool's configuration, ``{"mcpServers": {name: connection}}``, as the
MCP tools hold it, save it and connect with it.

A manifest never holds a secret, so a setting of a server that holds one -- a
header, an environment variable, ``auth``, a URL parameter -- refers to the
environment variable holding it, as ``"Bearer ${GITHUB_TOKEN}"``, which
:func:`with_env` expands when connecting: an MCP tool connects with the
values the variables had when it was made (see :func:`variables_set`). A
secret in a setting not named like
one, such as a command's argument, is not recognized: write it as ``${VAR}``
too. See :mod:`grafi.common.secrets`.
"""

import json
import os
from contextlib import AbstractAsyncContextManager
from typing import Annotated
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import Mapping
from typing import Self

from pydantic import BaseModel
from pydantic import BeforeValidator
from pydantic import Field
from pydantic import ModelWrapValidatorHandler
from pydantic import PlainSerializer
from pydantic import PrivateAttr
from pydantic import ValidationInfo
from pydantic import model_validator

from grafi.common.async_lifecycle import best_effort_exit
from grafi.common.manifest import ChecksOwnSecrets
from grafi.common.manifest import ManifestError
from grafi.common.manifest import ManifestPolicy
from grafi.common.manifest import save_refused
from grafi.common.secrets import env_variables_in
from grafi.common.secrets import expand_env
from grafi.common.secrets import held_secret

__all__ = ["MCPConfig", "connect"]


def with_env(config: Any, env: Mapping[str, str] = {}) -> Any:
    """An MCP configuration with each ``${VAR}`` in its strings replaced by the
    value of the environment variable ``VAR`` (the one ``env`` gives, else
    the environment's), as the client is given it.

    Raises:
        ValueError: If a variable referred to is not set, or empty.
    """
    if isinstance(config, str):
        return expand_env(config, env)
    if isinstance(config, Mapping):
        return {key: with_env(value, env) for key, value in config.items()}
    if isinstance(config, list):
        return [with_env(value, env) for value in config]
    return config


def variables_set(config: Any) -> Dict[str, str]:
    """The variables ``config`` refers to, as ``${VAR}``, that are set now,
    with their values: what an MCP tool made now connects with, as a tool
    keeps the key it was made with."""
    referred = env_variables_in(json.dumps(config, default=str))
    return {var: value for var in referred if (value := os.getenv(var))}


def connect(
    config: Mapping[str, Any], label: str, *, env: Mapping[str, str]
) -> AbstractAsyncContextManager[Any]:
    """A new connection to the servers ``config`` names, as fastmcp's client,
    with each ``${VAR}`` expanded (as ``env`` gives it, else as the
    environment does); released best-effort, as ``label``, so one failing to
    close fails no call it answered."""
    from fastmcp import Client  # The MCP tools' dependency, not grafi's.

    return best_effort_exit(Client(with_env(config, env)), f"{label} connection")


def check_mcp_secrets(config: Mapping[str, Any]) -> None:
    """Raise :class:`ManifestError` for a secret an MCP configuration holds as
    a value, naming the server; see this module."""
    servers = config.get("mcpServers") or {}
    for server, connection in servers.items() if isinstance(servers, Mapping) else ():
        held = held_secret("", connection, expands=True)
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
    """A configuration from a manifest holds no secret, and reads only the
    variables the manifest may."""
    policy = ManifestPolicy.of(info.context)
    if policy is not None and isinstance(config, Mapping):
        check_mcp_secrets(config)
        for var in env_variables_in(json.dumps(config)):  # JSON, as loaded.
            policy.check_env(var)
    return config


# An MCP configuration, saved as it is and connected with with_env(). It checks
# its secrets itself: its servers' names are not settings.
MCPConfig = Annotated[
    Dict[str, Any],
    PlainSerializer(_save_config, when_used="json"),
    BeforeValidator(_load_config),
    ChecksOwnSecrets(),
]


class MCPConnected(BaseModel):
    """What connects to MCP servers, as the MCP tools do: its configuration,
    and the values of the variables it refers to, read when it is made from
    data, which it connects with: it keeps the keys it was made with (one
    unset or empty then is read when it connects), as a copy of it, or it validated
    again, does. A dump refers to the variables; loading it reads them again.
    """

    mcp_config: MCPConfig = Field(default_factory=dict)

    _variables_read: Dict[str, str] = PrivateAttr(default_factory=dict)

    @model_validator(mode="wrap")
    @classmethod
    def _read_variables(
        cls, data: Any, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        component = handler(data)
        if isinstance(data, Mapping):
            component._variables_read = variables_set(component.mcp_config)
        return component

    def _connect(self) -> AbstractAsyncContextManager[Any]:
        """A new connection to its servers, with the values read when it was
        made (see :func:`connect`)."""
        label = getattr(self, "name", None) or type(self).__name__
        return connect(self.mcp_config, label, env=self._variables_read)

    @classmethod
    async def _listed(
        cls,
        kwargs: Mapping[str, Any],
        listing: Callable[[Any], Awaitable[Dict[str, Any]]],
    ) -> Self:
        """The component ``kwargs`` make, with what ``listing(client)`` gives
        from its servers; it keeps the variables' values they were listed
        with, read once, though one changes, for another session, meanwhile."""
        if not kwargs.get("mcp_config"):
            raise ValueError(
                f"{cls.__name__} has no servers: give them with "
                ".connections({name: connection, ...})."
            )
        # Made from its arguments first, so they are checked before a server
        # is started, with the one reading of the variables it keeps.
        probe = cls(**kwargs)
        async with probe._connect() as client:
            listed = await listing(client)
        component = cls(**{**kwargs, **listed})
        component._variables_read = probe._variables_read
        return component
