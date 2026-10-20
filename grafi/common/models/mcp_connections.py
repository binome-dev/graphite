from datetime import timedelta
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Literal
from typing import Optional

import httpx
from typing_extensions import TypedDict


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
