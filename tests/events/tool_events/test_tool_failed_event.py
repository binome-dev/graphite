from typing import Any

import pytest

from grafi.common.events.component_events import ToolFailedEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


@pytest.fixture
def tool_failed_event() -> Any:
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


@pytest.fixture
def tool_failed_event_with_details(tool_failed_event) -> Any:
    return tool_failed_event.model_copy(
        update={
            "error_details": {
                "error_type": "FunctionCallException",
                "error_module": "grafi.common.exceptions.tool_exceptions",
                "message": "function call blew up",
                "tool_name": "test_tool",
                "cause": {"error_type": "ValueError", "message": "root boom"},
                "traceback": "Traceback (most recent call last): ...",
            }
        }
    )


def test_tool_failed_event_to_dict(tool_failed_event, tool_failed_event_dict):
    assert tool_failed_event.to_dict() == tool_failed_event_dict


def test_tool_failed_event_from_dict(tool_failed_event_dict, tool_failed_event):
    assert ToolFailedEvent.from_dict(tool_failed_event_dict) == tool_failed_event


def test_tool_failed_event_omits_error_details_when_absent(tool_failed_event):
    # Backward compatibility: with no structured details, the key is absent and
    # the serialized shape is unchanged.
    assert "error_details" not in tool_failed_event.to_dict()["data"]


def test_tool_failed_event_to_dict_includes_error_details(
    tool_failed_event_with_details,
):
    data = tool_failed_event_with_details.to_dict()["data"]
    assert data["error"] == "error"  # human-readable string preserved
    assert data["error_details"]["error_type"] == "FunctionCallException"
    assert data["error_details"]["cause"]["error_type"] == "ValueError"


def test_tool_failed_event_error_details_round_trip(tool_failed_event_with_details):
    restored = ToolFailedEvent.from_dict(tool_failed_event_with_details.to_dict())
    assert restored == tool_failed_event_with_details
    assert restored.error_details["cause"]["message"] == "root boom"
