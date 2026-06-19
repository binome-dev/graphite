"""Tests for the ExecutionServices DI port (Phase 3)."""

from unittest.mock import MagicMock

from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import default_execution_services


def test_execution_services_is_immutable():
    svc = ExecutionServices(event_store=EventStoreInMemory(), tracer=MagicMock())
    try:
        svc.event_store = EventStoreInMemory()  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised, "ExecutionServices should be frozen"


def test_default_execution_services_reads_container():
    from grafi.common.containers.container import container

    store = EventStoreInMemory()
    tracer = MagicMock()
    prev_store, prev_tracer = container._event_store, container._tracer
    container.register_event_store(store)
    container.register_tracer(tracer)
    try:
        svc = default_execution_services()
        assert svc.event_store is store
        assert svc.tracer is tracer
    finally:
        container._event_store = prev_store
        container._tracer = prev_tracer
