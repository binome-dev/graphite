import pytest
from pydantic import ValidationError

from grafi.common.events.component_events import ToolFailedEvent
from grafi.common.events.event_codec import default_event_codec
from tests.events.event_fixtures import HELLO_JSON
from tests.events.event_fixtures import INVOKE_CONTEXT_JSON
from tests.events.event_fixtures import TIMESTAMP
from tests.events.event_fixtures import TIMESTAMP_JSON
from tests.events.event_fixtures import hello
from tests.events.event_fixtures import invoke_context
from tests.events.event_fixtures import round_trip
from tests.events.event_fixtures import stored

ERROR_DETAILS = {
    "error_type": "FunctionCallException",
    "error_module": "grafi.common.exceptions.tool_exceptions",
    "message": "function call blew up",
    "tool_name": "test_tool",
    "cause": {"error_type": "ValueError", "message": "root boom"},
    "traceback": "Traceback (most recent call last): ...",
}


@pytest.fixture
def tool_failed_event() -> ToolFailedEvent:
    return ToolFailedEvent(
        event_id="test_id",
        timestamp=TIMESTAMP,
        id="test_id",
        name="test_tool",
        type="test_type",
        invoke_context=invoke_context(),
        input_data=[hello()],
        error="error",
    )


@pytest.fixture
def tool_failed_event_json() -> dict:
    return {
        "event_id": "test_id",
        "event_version": 2,
        "invoke_context": INVOKE_CONTEXT_JSON,
        "event_type": "ToolFailed",
        "timestamp": TIMESTAMP_JSON,
        "id": "test_id",
        "name": "test_tool",
        "type": "test_type",
        "input_data": [HELLO_JSON],
        "error": "error",
        "error_details": None,
    }


@pytest.fixture
def tool_failed_event_v1() -> dict:
    """The event as version 1 stored it (ToolFailedEvent.to_dict)."""
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
                }
            ],
            "error": "error",
        },
    }


@pytest.fixture
def tool_failed_event_with_details(tool_failed_event) -> ToolFailedEvent:
    return tool_failed_event.model_copy(update={"error_details": ERROR_DETAILS})


def test_tool_failed_event_encodes_flat_json(tool_failed_event, tool_failed_event_json):
    assert default_event_codec.encode(tool_failed_event) == tool_failed_event_json
    assert stored(tool_failed_event) == tool_failed_event_json


def test_tool_failed_event_round_trip(tool_failed_event):
    decoded = round_trip(tool_failed_event)
    assert type(decoded) is ToolFailedEvent
    assert decoded == tool_failed_event


def test_tool_failed_event_decodes_version_1(tool_failed_event_v1, tool_failed_event):
    decoded = default_event_codec.decode(tool_failed_event_v1)
    assert type(decoded) is ToolFailedEvent
    assert decoded == tool_failed_event
    assert decoded.error_details is None


def test_tool_failed_event_encodes_error_details(tool_failed_event_with_details):
    encoded = stored(tool_failed_event_with_details)
    assert encoded["error"] == "error"  # The human-readable text, kept.
    assert encoded["error_details"] == ERROR_DETAILS


def test_tool_failed_event_error_details_round_trip(tool_failed_event_with_details):
    restored = round_trip(tool_failed_event_with_details)
    assert restored == tool_failed_event_with_details
    assert restored.error_details["cause"]["message"] == "root boom"


def test_tool_failed_event_decodes_version_1_error_details(
    tool_failed_event_v1, tool_failed_event_with_details
):
    # Version 1 wrote error_details in data only when they were captured.
    tool_failed_event_v1["data"]["error_details"] = ERROR_DETAILS
    decoded = default_event_codec.decode(tool_failed_event_v1)
    assert decoded == tool_failed_event_with_details


def test_tool_failed_event_error_is_text(tool_failed_event):
    # The error is recorded as text: an exception is not stored as itself.
    with pytest.raises(ValidationError):
        ToolFailedEvent(**{**dict(tool_failed_event), "error": ValueError("boom")})
