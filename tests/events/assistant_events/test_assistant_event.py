import pytest

from grafi.common.events.assistant_events.assistant_event import ASSISTANT_ID
from grafi.common.events.assistant_events.assistant_event import ASSISTANT_NAME
from grafi.common.events.assistant_events.assistant_event import ASSISTANT_TYPE
from grafi.common.events.assistant_events.assistant_event import AssistantEvent
from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.models.invoke_context import InvokeContext


@pytest.fixture
def assistant_event() -> AssistantEvent:
    return AssistantEvent(
        event_id="test_id",
        event_type="AssistantInvoke",
        timestamp="2009-02-13T23:31:30+00:00",
        assistant_id="test_id",
        assistant_name="test_assistant",
        assistant_type="test_type",
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
    )


@pytest.fixture
def assistant_event_dict():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "AssistantInvoke",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            ASSISTANT_ID: "test_id",
            ASSISTANT_NAME: "test_assistant",
            ASSISTANT_TYPE: "test_type",
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
    }


def test_assistant_event_dict(assistant_event: AssistantEvent, assistant_event_dict):
    assert assistant_event.assistant_event_dict() == assistant_event_dict


def test_assistant_event_base(assistant_event_dict, assistant_event):
    assert AssistantEvent.assistant_event_base(assistant_event_dict) == assistant_event
