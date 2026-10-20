import pytest

from grafi.common.events.component_events import WorkflowInvokeEvent
from grafi.common.events.event_codec import default_event_codec
from tests.events.event_fixtures import INVOKE_CONTEXT_JSON
from tests.events.event_fixtures import INVOKE_CONTEXT_V1
from tests.events.event_fixtures import TIMESTAMP
from tests.events.event_fixtures import TIMESTAMP_JSON
from tests.events.event_fixtures import invoke_context
from tests.events.event_fixtures import request
from tests.events.event_fixtures import request_json
from tests.events.event_fixtures import request_v1
from tests.events.event_fixtures import round_trip
from tests.events.event_fixtures import stored


@pytest.fixture
def workflow_invoke_event() -> WorkflowInvokeEvent:
    return WorkflowInvokeEvent(
        event_id="test_id",
        timestamp=TIMESTAMP,
        id="test_id",
        name="test_workflow",
        type="test_type",
        invoke_context=invoke_context(),
        input_data=request(),
    )


@pytest.fixture
def workflow_invoke_event_json() -> dict:
    return {
        "event_id": "test_id",
        "event_version": 2,
        "invoke_context": INVOKE_CONTEXT_JSON,
        "event_type": "WorkflowInvoke",
        "timestamp": TIMESTAMP_JSON,
        "id": "test_id",
        "name": "test_workflow",
        "type": "test_type",
        "input_data": request_json(),
    }


@pytest.fixture
def workflow_invoke_event_v1() -> dict:
    """The event as version 1 stored it (WorkflowInvokeEvent.to_dict)."""
    return {
        "event_id": "test_id",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "WorkflowInvoke",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
            "id": "test_id",
            "name": "test_workflow",
            "type": "test_type",
            "invoke_context": INVOKE_CONTEXT_V1,
        },
        "data": {
            "input_data": request_v1(),
        },
    }


def test_workflow_invoke_event_encodes_flat_json(
    workflow_invoke_event, workflow_invoke_event_json
):
    assert (
        default_event_codec.encode(workflow_invoke_event) == workflow_invoke_event_json
    )
    assert stored(workflow_invoke_event) == workflow_invoke_event_json


def test_workflow_invoke_event_round_trip(workflow_invoke_event):
    decoded = round_trip(workflow_invoke_event)
    assert type(decoded) is WorkflowInvokeEvent
    assert decoded == workflow_invoke_event


def test_workflow_invoke_event_decodes_version_1(
    workflow_invoke_event_v1, workflow_invoke_event
):
    decoded = default_event_codec.decode(workflow_invoke_event_v1)
    assert type(decoded) is WorkflowInvokeEvent
    assert decoded == workflow_invoke_event
