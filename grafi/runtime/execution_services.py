"""Runtime-only dependency container and its request-scoped binding.

``ExecutionServices`` holds the three live runtime dependencies an invocation
needs -- the event store, the tracer, and the error reporter. It is owned by
:class:`~grafi.runtime.runtime.GrafiRuntime`, bound to a request-scoped
``ContextVar`` for the duration of each ``invoke``, and read through
:func:`current_services`.

It is deliberately NOT a Pydantic model and exposes no serialization: it must
never be persisted into an event, a manifest, or an ``InvokeContext``. Request
metadata (serializable) and runtime services (never serialized) are kept
strictly separate.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from contextvars import Token
from dataclasses import dataclass
from dataclasses import field
from typing import Iterator
from typing import Optional

from loguru import logger
from opentelemetry.trace import NoOpTracer
from opentelemetry.trace import Tracer

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
    """Immutable bundle of the live runtime dependencies for one runtime.

    Each field has an in-process default, so ``ExecutionServices()`` is a ready
    dev/test bundle and any field can be overridden with a normal keyword --
    ``ExecutionServices(event_store=EventStorePostgres(...))``. There is no
    separate factory; the dataclass *is* the default.

    The fields are excluded from ``repr`` so a stray ``repr(services)`` (or an
    object that embeds one) cannot leak a database URL, client, or other
    infrastructure detail into a log or persisted record.

    Note: the default ``event_store`` is in-memory (lost on exit) and the default
    ``tracer`` is a no-op (spans discarded) -- fine for local/test, but
    production should pass a durable store and a real tracer explicitly.
    """

    event_store: EventStore = field(default_factory=EventStoreInMemory, repr=False)
    tracer: Tracer = field(default_factory=NoOpTracer, repr=False)
    error_reporter: ErrorReporter = field(default_factory=ErrorReporter, repr=False)


# Request-scoped binding. Holds the services for the currently executing
# invocation. ``None`` outside any ``GrafiRuntime.invoke`` / ``bind_services``
# scope -- there is intentionally no process-global default.
_current_services: ContextVar[Optional[ExecutionServices]] = ContextVar(
    "grafi_current_services", default=None
)


def current_services() -> ExecutionServices:
    """Return the ``ExecutionServices`` bound for the current invocation.

    Raises ``RuntimeError`` when called outside a bound scope, rather than
    silently constructing a process-global default. Drive invocations through
    :meth:`GrafiRuntime.invoke` (or wrap direct component calls in
    :func:`bind_services`).
    """
    services = _current_services.get()
    if services is None:
        raise RuntimeError(
            "No ExecutionServices bound for the current invocation. Invoke through "
            "GrafiRuntime.invoke(...), or wrap direct component calls in "
            "grafi.runtime.bind_services(...)."
        )
    return services


@contextlib.contextmanager
def bind_services(services: ExecutionServices) -> Iterator[ExecutionServices]:
    """Bind ``services`` to the request scope for the duration of the block.

    Uses ``ContextVar`` set/reset (capture-and-restore), so nested bindings
    restore the previous value on exit. ``asyncio`` tasks created inside the
    block inherit the binding because ``create_task``/``gather`` snapshot the
    current context.
    """
    token: Token[Optional[ExecutionServices]] = _current_services.set(services)
    try:
        yield services
    finally:
        _current_services.reset(token)
