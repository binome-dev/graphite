import pytest

from grafi.common.event_stores.event_store import EventStore
from grafi.common.models.invoke_context import InvokeContext
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services


@pytest.fixture(autouse=True)
def bound_services() -> ExecutionServices:
    """Bind a fresh default ExecutionServices for every test.

    Replaces the old process-global container default: ``current_services()`` is
    available throughout each test (and in the asyncio tasks it spawns, because
    this sync fixture binds the ContextVar before the event loop runs the test
    coroutine). ``ExecutionServices()`` supplies the in-process defaults; tests
    that need a specific store or tracer bind their own scope with
    ``grafi.runtime.bind_services(ExecutionServices(...))``, which shadows this.
    """
    services = ExecutionServices()
    with bind_services(services):
        yield services


@pytest.fixture
def event_store(bound_services: ExecutionServices) -> EventStore:
    """The EventStore bound for the current test."""
    return bound_services.event_store


@pytest.fixture
def invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id="invoke_id",
        assistant_request_id="assistant_request_id",
    )
