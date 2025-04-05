import pytest

from grafi.common.events.assistant_events.assistant_invoke_event import (
    AssistantInvokeEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message


@pytest.fixture
def assistant_invoke_event() -> AssistantInvokeEvent:
    return AssistantInvokeEvent(
        event_id="test_id",
        event_type="AssistantInvoke",
        timestamp="2009-02-13T23:31:30+00:00",
        assistant_id="test_id",
        assistant_name="test_assistant",
        assistant_type="test_type",
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
        execution_context=ExecutionContext(
            conversation_id="conversation_id",
            execution_id="execution_id",
            assistant_request_id="assistant_request_id",
        ),
    )


@pytest.fixture
def assistant_invoke_event_dict():
    return {
        "event_id": "test_id",
        "event_type": "AssistantInvoke",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
            "assistant_id": "test_id",
            "assistant_name": "test_assistant",
            "assistant_type": "test_type",
            "execution_context": {
                "conversation_id": "conversation_id",
                "execution_id": "execution_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": {
            "input_data": '[{"content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "role": "user", "annotations": null, "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "tool_call_id": null, "tools": null, "functions": null}]'
        },
    }


def test_assistant_invoke_event_dict(
    assistant_invoke_event: AssistantInvokeEvent, assistant_invoke_event_dict
):
    assert assistant_invoke_event.to_dict() == assistant_invoke_event_dict


def test_assistant_invoke_event(assistant_invoke_event_dict, assistant_invoke_event):
    assert (
        AssistantInvokeEvent.from_dict(assistant_invoke_event_dict)
        == assistant_invoke_event
    )
