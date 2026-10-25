import pytest

from grafi.common.events.component_events import ToolInvokeEvent
from grafi.common.events.event_codec import default_event_codec
from tests.events.event_fixtures import HELLO_JSON
from tests.events.event_fixtures import INVOKE_CONTEXT_JSON
from tests.events.event_fixtures import TIMESTAMP
from tests.events.event_fixtures import TIMESTAMP_JSON
from tests.events.event_fixtures import hello
from tests.events.event_fixtures import invoke_context
from tests.events.event_fixtures import round_trip
from tests.events.event_fixtures import stored


@pytest.fixture
def tool_invoke_event() -> ToolInvokeEvent:
    return ToolInvokeEvent(
        event_id="test_id",
        timestamp=TIMESTAMP,
        id="test_id",
        name="test_tool",
        type="test_type",
        invoke_context=invoke_context(),
        input_data=[hello()],
    )


@pytest.fixture
def tool_invoke_event_json() -> dict:
    return {
        "event_id": "test_id",
        "event_version": 2,
        "invoke_context": INVOKE_CONTEXT_JSON,
        "event_type": "ToolInvoke",
        "timestamp": TIMESTAMP_JSON,
        "id": "test_id",
        "name": "test_tool",
        "type": "test_type",
        "input_data": [HELLO_JSON],
    }


@pytest.fixture
def tool_invoke_event_v1() -> dict:
    """The event as version 1 stored it (ToolInvokeEvent.to_dict)."""
    return {
        "event_id": "test_id",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "ToolInvoke",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
            "id": "test_id",
            "name": "test_tool",
            "type": "test_type",
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
                "kwargs": {},
            },
        },
        "data": {
            "input_data": [
                {
                    "name": None,
                    "message_id": "ea72df51439b42e4a43b217c9bca63f5",
                    "timestamp": 1737138526189505000,
                    "content": "Hello, my name is Grafi, how are you doing?",
                    "refusal": None,
                    "annotations": None,
                    "audio": None,
                    "role": "user",
                    "tool_call_id": None,
                    "tools": None,
                    "function_call": None,
                    "tool_calls": None,
                }
            ]
        },
    }


def test_tool_invoke_event_encodes_flat_json(tool_invoke_event, tool_invoke_event_json):
    assert default_event_codec.encode(tool_invoke_event) == tool_invoke_event_json
    assert stored(tool_invoke_event) == tool_invoke_event_json


def test_tool_invoke_event_round_trip(tool_invoke_event):
    decoded = round_trip(tool_invoke_event)
    assert type(decoded) is ToolInvokeEvent
    assert decoded == tool_invoke_event


def test_tool_invoke_event_decodes_version_1(tool_invoke_event_v1, tool_invoke_event):
    decoded = default_event_codec.decode(tool_invoke_event_v1)
    assert type(decoded) is ToolInvokeEvent
    assert decoded == tool_invoke_event


def test_tool_invoke_event_decodes_version_1_with_component_type(
    tool_invoke_event_v1, tool_invoke_event
):
    # Some version 1 events also kept their component's type in the context.
    tool_invoke_event_v1["event_context"]["component_type"] = "Tool"
    assert default_event_codec.decode(tool_invoke_event_v1) == tool_invoke_event
