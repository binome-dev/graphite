"""Injected runtime dependencies for execution.

``ExecutionServices`` is the dependency-inversion port through which execution
code obtains its event store and tracer, instead of reaching for the global
``container`` singleton directly. The container remains the default composition
root: ``default_execution_services()`` reads today's defaults from it, so
adoption can proceed incrementally without changing existing behavior.
"""

from dataclasses import dataclass

from opentelemetry.trace import Tracer

from grafi.common.event_stores.event_store import EventStore


@dataclass(frozen=True)
class ExecutionServices:
    """Immutable bundle of the runtime dependencies execution needs."""

    event_store: EventStore
    tracer: Tracer


def default_execution_services() -> ExecutionServices:
    """Build services from the global container (the default composition root).

    Imported lazily so this module does not depend on the container at import
    time and can be used as a seam for explicit injection later.
    """
    from grafi.common.containers.container import container

    return ExecutionServices(event_store=container.event_store, tracer=container.tracer)
