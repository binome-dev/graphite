"""The services an invocation runs with, and how it finds them.

``ExecutionServices`` holds the live runtime dependencies an invocation needs
-- the event store, the tracer, the error reporter, and the executor sync tool
code runs in. Components read
them through :func:`current_services`: those bound for the invocation, by
:func:`bind_services` or :class:`~grafi.runtime.runtime.GrafiRuntime`, else the
process default, which :func:`set_default_services` sets once at startup, as
``setup_tracing`` sets the tracer provider.

It is deliberately NOT a Pydantic model and exposes no serialization: it must
never be persisted into an event, a manifest, or an ``InvokeContext``. Request
metadata (serializable) and runtime services (never serialized) are kept
strictly separate.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from contextvars import Token
from dataclasses import dataclass
from dataclasses import field
from functools import partial
from typing import Any
from typing import Optional

from loguru import logger
from opentelemetry.trace import Tracer
from opentelemetry.trace import get_tracer

from grafi.common.env import env_bool
from grafi.common.event_stores.event_store import EventStore
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory


class ErrorReporter:
    """Emits one concise, id-bearing execution-error line through Loguru.

    The lifecycle decorator builds a one-line ``message`` carrying the failing
    component, the error, and the conversation/invoke/assistant_request/error
    ids. The full structured record -- cause chain, traceback, component fields
    -- is persisted to the event store, so the log only needs to point at it via
    those ids.

    This is the default reporter: it logs at the requested level and configures
    no sinks (a library must not own the application's logging). Subclass and
    override :meth:`report` to route execution errors elsewhere. ``report`` must
    not raise.
    """

    def report(self, message: str, *, level: str = "error") -> None:
        """Emit one record. ``level`` is ``"error"`` for a failure or
        ``"warning"`` for a secondary diagnostic (e.g. a persistence failure)."""
        # Resolve the level method defensively; unknown levels fall back to error.
        emit = getattr(logger, level, None)
        if not callable(emit):
            emit = logger.error
        # Pass the message as an argument so any braces in it are not
        # re-interpreted as Loguru format placeholders.
        emit("{}", message)


@dataclass(frozen=True, slots=True)
class ExecutionServices:
    """Immutable bundle of the live services an invocation runs with.

    Each field has an in-process value by default, so ``ExecutionServices()``
    is a ready in-process bundle, and any field can be given with a keyword:
    ``ExecutionServices(event_store=EventStorePostgres(...))``.

    The fields are excluded from ``repr`` so a stray ``repr(services)`` (or an
    object that embeds one) cannot leak a database URL, client, or other
    infrastructure detail into a log or persisted record.

    Note: the default ``event_store`` is in-memory (lost on exit) -- fine for
    local/test, but production should pass a durable store. The default
    ``tracer`` is OpenTelemetry's global one: it records once a tracer provider
    is set, by ``setup_tracing`` or the application, and is a no-op until then.
    """

    event_store: EventStore = field(default_factory=EventStoreInMemory, repr=False)
    tracer: Tracer = field(default_factory=partial(get_tracer, "grafi"), repr=False)
    error_reporter: ErrorReporter = field(default_factory=ErrorReporter, repr=False)
    # Where sync tool code runs (see grafi.tools.results): a thread pool, as it
    # runs in this process; None for grafi's own, one for each event loop. Its
    # owner shuts it down.
    executor: Optional[ThreadPoolExecutor] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not hasattr(self.tracer, "start_span"):
            provider = hasattr(self.tracer, "get_tracer")
            raise TypeError(
                f"ExecutionServices.tracer is a tracer, not a "
                f"{type(self.tracer).__name__}"
                + (
                    ": setup_tracing() returns the provider it sets for the "
                    "process, which grafi's default tracer uses, so leave tracer "
                    "out (or pass provider.get_tracer(...))."
                    if provider
                    else "."
                )
            )

    async def aclose(self) -> None:
        """Release what the services hold, such as the event store's pool, at
        shutdown. Spans are flushed by the tracer provider, at exit."""
        await self.event_store.aclose()

    async def __aenter__(self) -> ExecutionServices:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()


# The services bound for the current invocation, if any.
_current_services: ContextVar[Optional[ExecutionServices]] = ContextVar(
    "grafi_current_services", default=None
)
_default_services: Optional[ExecutionServices] = None
_default_lock = threading.Lock()


def current_services() -> ExecutionServices:
    """The services bound for the current invocation, else the process default:
    those given to :func:`set_default_services`, or, from first use, in-process
    ones with an in-memory event store, unless ``GRAFI_STRICT_SERVICES`` makes
    that raise ``RuntimeError``."""
    return _current_services.get() or _default_services or _create_default()


def set_default_services(services: ExecutionServices) -> None:
    """Make ``services`` the process default: what every invocation not bound to
    others runs with. Call it once at startup, before the first invocation."""
    global _default_services
    with _default_lock:
        replaced, _default_services = _default_services is not None, services
    if replaced:  # Logged without the lock: a log sink may read the services.
        logger.warning(
            "set_default_services replaced earlier default services: set them "
            "once, at startup"
        )


def _create_default() -> ExecutionServices:
    global _default_services
    with _default_lock:
        if _default_services is not None:
            return _default_services
        if env_bool("GRAFI_STRICT_SERVICES"):
            raise RuntimeError(
                "No services set, and GRAFI_STRICT_SERVICES forbids in-memory "
                "ones: call grafi.runtime.set_default_services(...) at startup."
            )
        _default_services = created = ExecutionServices()
    # Logged without the lock: a log sink may read the services.
    logger.warning(
        "grafi keeps events in memory, where they are lost on exit: call "
        "grafi.runtime.set_default_services(...) at startup with a durable "
        "event store."
    )
    return created


class bind_services:
    """Bind ``services`` to the invocations started in the block.

    Uses ``ContextVar`` set/reset (capture-and-restore), so nested bindings
    restore the previous value on exit. ``asyncio`` tasks created inside the
    block inherit the binding because ``create_task``/``gather`` snapshot the
    current context. Leave the block in the context that entered it: an async
    generator binds around each step, not across a ``yield`` (see
    :meth:`GrafiRuntime.invoke`). A plain class, as streams enter it per step.
    """

    __slots__ = ("_services", "_token")

    def __init__(self, services: ExecutionServices) -> None:
        self._services = services
        self._token: Optional[Token[Optional[ExecutionServices]]] = None

    def __enter__(self) -> ExecutionServices:
        if self._token is not None:
            raise RuntimeError("This binding is already entered")
        self._token = _current_services.set(self._services)
        return self._services

    def __exit__(self, *exc_info: Any) -> None:
        token, self._token = self._token, None
        if token is not None:
            _current_services.reset(token)
