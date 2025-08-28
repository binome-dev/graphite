import pytest

from grafi.common.events.component_events import ToolFailedEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


@pytest.fixture
def tool_failed_event() -> ToolFailedEvent:
    return ToolFailedEvent(
        event_id="test_id",
        event_type="ToolFailed",
        timestamp="2009-02-13T23:31:30+00:00",
        id="test_id",
        name="test_tool",
        type="test_type",
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
        input_data=[
            Message(
                message_id="ea72df51439b42e4a43b217c9bca63f5",
                timestamp=1737138526189505000,
                role="user",
                content="Hello, my name is Grafi, how are you doing?",
                name=None,
                functions=None,
                function_call=None,
            )
        ],
        error="error",
    )


@pytest.fixture
def tool_failed_event_dict():
    return {
        "event_id": "test_id",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "ToolFailed",
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
                    "is_streaming": False,
                }
            ],
            "error": "error",
        },
    }


def test_tool_failed_event_to_dict(
    tool_failed_event: ToolFailedEvent, tool_failed_event_dict
):
    assert tool_failed_event.to_dict() == tool_failed_event_dict


def test_tool_failed_event_from_dict(tool_failed_event_dict, tool_failed_event):
    assert ToolFailedEvent.from_dict(tool_failed_event_dict) == tool_failed_event
