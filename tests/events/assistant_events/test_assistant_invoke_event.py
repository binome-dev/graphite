import pytest

from grafi.common.events.component_events import AssistantInvokeEvent
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
def assistant_invoke_event() -> AssistantInvokeEvent:
    return AssistantInvokeEvent(
        event_id="test_id",
        timestamp=TIMESTAMP,
        id="test_id",
        name="test_assistant",
        type="test_type",
        invoke_context=invoke_context(),
        input_data=request(),
    )


@pytest.fixture
def assistant_invoke_event_json() -> dict:
    return {
        "event_id": "test_id",
        "event_version": 2,
        "invoke_context": INVOKE_CONTEXT_JSON,
        "event_type": "AssistantInvoke",
        "timestamp": TIMESTAMP_JSON,
        "id": "test_id",
        "name": "test_assistant",
        "type": "test_type",
        "input_data": request_json(),
    }


@pytest.fixture
def assistant_invoke_event_v1() -> dict:
    """The event as version 1 stored it (AssistantInvokeEvent.to_dict)."""
    return {
        "event_id": "test_id",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "AssistantInvoke",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
            "id": "test_id",
            "name": "test_assistant",
            "type": "test_type",
            "invoke_context": INVOKE_CONTEXT_V1,
            "model": "gpt-4o",
        },
        "data": {
            "input_data": request_v1(),
        },
    }


def test_assistant_invoke_event_encodes_flat_json(
    assistant_invoke_event, assistant_invoke_event_json
):
    assert (
        default_event_codec.encode(assistant_invoke_event)
        == assistant_invoke_event_json
    )
    assert stored(assistant_invoke_event) == assistant_invoke_event_json


def test_assistant_invoke_event_round_trip(assistant_invoke_event):
    decoded = round_trip(assistant_invoke_event)
    assert type(decoded) is AssistantInvokeEvent
    assert decoded == assistant_invoke_event


def test_assistant_invoke_event_decodes_version_1(
    assistant_invoke_event_v1, assistant_invoke_event
):
    decoded = default_event_codec.decode(assistant_invoke_event_v1)
    assert type(decoded) is AssistantInvokeEvent
    assert decoded == assistant_invoke_event
