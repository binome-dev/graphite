import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterator
from typing import Literal
from typing import Mapping
from typing import Optional
from typing import Tuple
from urllib.parse import parse_qsl
from urllib.parse import urlsplit

import httpx
from pydantic import BeforeValidator
from pydantic import PlainSerializer
from pydantic import ValidationInfo
from typing_extensions import TypedDict

from grafi.common.manifest import ManifestError
from grafi.common.manifest import check_manifest_env
from grafi.common.manifest import is_env_reference
from grafi.common.manifest import loading_manifest
from grafi.common.manifest import refuse_save
from grafi.common.manifest import secret_name
from grafi.common.manifest import holds_url_password

EncodingErrorHandler = Literal["strict", "ignore", "replace"]


class StdioConnection(TypedDict):
    transport: Literal["stdio"]

    command: str
    """The executable to run to start the server."""

    args: list[str]
    """Command line arguments to pass to the executable."""

    env: dict[str, str] | None
    """The environment to use when spawning the process."""

    cwd: str | Path | None
    """The working directory to use when spawning the process."""

    encoding: str
    """The text encoding used when sending/receiving messages to the server."""

    encoding_error_handler: EncodingErrorHandler
    """
    The text encoding error handler.

    See https://docs.python.org/3/library/codecs.html#codec-base-classes for
    explanations of possible values.
    """

    session_kwargs: dict[str, Any] | None
    """Additional keyword arguments to pass to the ClientSession."""


class SSEConnection(TypedDict):
    transport: Literal["sse"]

    url: str
    """The URL of the SSE endpoint to connect to."""

    headers: dict[str, Any] | None
    """HTTP headers to send to the SSE endpoint."""

    timeout: float
    """HTTP timeout."""

    sse_read_timeout: float
    """SSE read timeout."""

    session_kwargs: dict[str, Any] | None
    """Additional keyword arguments to pass to the ClientSession."""

    httpx_client_factory: Optional[
        Callable[
            [Optional[dict[str, str]], Optional[httpx.Timeout], Optional[httpx.Auth]],
            httpx.AsyncClient,
        ]
    ]
    """Custom factory for httpx.AsyncClient (optional)."""


class StreamableHttpConnection(TypedDict):
    transport: Literal["streamable_http"]

    url: str
    """The URL of the endpoint to connect to."""

    headers: dict[str, Any] | None
    """HTTP headers to send to the endpoint."""

    timeout: timedelta
    """HTTP timeout."""

    sse_read_timeout: timedelta
    """How long (in seconds) the client will wait for a new event before disconnecting.
    All other HTTP operations are controlled by `timeout`."""

    terminate_on_close: bool
    """Whether to terminate the session on close."""

    session_kwargs: dict[str, Any] | None
    """Additional keyword arguments to pass to the ClientSession."""

    httpx_client_factory: Optional[
        Callable[
            [Optional[dict[str, str]], Optional[httpx.Timeout], Optional[httpx.Auth]],
            httpx.AsyncClient,
        ]
    ]
    """Custom factory for httpx.AsyncClient (optional)."""


class WebsocketConnection(TypedDict):
    transport: Literal["websocket"]

    url: str
    """The URL of the Websocket endpoint to connect to."""

    session_kwargs: dict[str, Any] | None
    """Additional keyword arguments to pass to the ClientSession"""


Connection = (
    StdioConnection | SSEConnection | StreamableHttpConnection | WebsocketConnection
)


# A reference to an environment variable in an MCP connection's strings.
_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

def with_env(config: Any) -> Any:
    """An MCP configuration with each ``${VAR}`` in its strings replaced by the
    value of the environment variable ``VAR``, as the client is given it."""
    if isinstance(config, str):
        return _ENV_REFERENCE.sub(_env_value, config)
    if isinstance(config, Mapping):
        return {key: with_env(value) for key, value in config.items()}
    if isinstance(config, list):
        return [with_env(value) for value in config]
    return config


def _env_value(reference: "re.Match[str]") -> str:
    value = os.getenv(reference[1])
    if value is None:
        raise ValueError(
            f"An MCP connection refers to the environment variable {reference[1]}, "
            "which is not set."
        )
    return value


def _settings(value: Any, name: str = "") -> Iterator[Tuple[str, Any]]:
    """Every named setting in a connection, nested ones and a URL's query
    parameters included."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            # Within one named like a secret, all is under its name.
            yield from _settings(item, name if secret_name(name) else str(key))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _settings(item, name)
    else:
        yield name, value
        if name == "url" and isinstance(value, str):
            yield from parse_qsl(urlsplit(value).query)


def check_mcp_secrets(config: Mapping[str, Any]) -> None:
    """Raise :class:`ManifestError` for a secret an MCP configuration holds as
    a value: a setting named like one (a header, an environment variable, a
    URL parameter, ``auth``...) must refer to the environment variable holding
    it, as ``"Bearer ${GITHUB_TOKEN}"``, which is expanded when connecting. A
    secret in a setting not so named, such as a command's argument, is not
    recognized: write it as ``${VAR}`` too."""
    servers = config.get("mcpServers") or {}
    for server, connection in servers.items() if isinstance(servers, Mapping) else ():
        for name, value in _settings(connection):
            if isinstance(value, str) and (
                (value and secret_name(name) and not is_env_reference(value))
                or (name == "url" and holds_url_password(value))
            ):
                raise refuse_save(
                    ManifestError(
                        f"The MCP server {server!r} has {name!r} set to a value, "
                        "and a manifest never holds a secret: refer to an "
                        'environment variable holding it, as "${VAR}", which is '
                        "expanded when connecting."
                    )
                )


def _save_config(config: Dict[str, Any]) -> Dict[str, Any]:
    check_mcp_secrets(config)
    return config


def _load_config(config: Any, info: ValidationInfo) -> Any:
    """A configuration from a manifest holds no secret, and reads only the
    variables it may."""
    if loading_manifest(info.context) and isinstance(config, Mapping):
        check_mcp_secrets(config)
        for _, value in _settings(config):
            if isinstance(value, str):
                for var in _ENV_REFERENCE.findall(value):
                    check_manifest_env(info.context, var)
    return config


# An MCP configuration, ``{"mcpServers": {name: connection}}``, saved as it is
# (see check_mcp_secrets()), and connected with with_env().
MCPConfig = Annotated[
    Dict[str, Any],
    PlainSerializer(_save_config, when_used="json"),
    BeforeValidator(_load_config),
]
