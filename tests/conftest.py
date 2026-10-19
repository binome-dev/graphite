import pytest

from grafi.common.event_stores.event_store import EventStore
from grafi.common.models.invoke_context import InvokeContext
from grafi.runtime import execution_services
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services


@pytest.fixture(autouse=True)
def bound_services() -> ExecutionServices:
    """Bind fresh in-process services for every test, so tests never share a
    store through the process default.

    The binding holds throughout the test, and in the asyncio tasks it starts:
    this sync fixture binds before the event loop runs the test coroutine. A
    test needing other services binds them with ``bind_services``. A test that
    escaped the binding, and so created the process default, fails.
    """
    services = ExecutionServices()
    with bind_services(services):
        yield services
    escaped = execution_services._default_services
    execution_services._default_services = None  # Spare the tests after it.
    assert escaped is None, "the test ran outside its bound services"


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
