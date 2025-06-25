import pytest

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.tool_events.tool_event import TOOL_ID
from grafi.common.events.tool_events.tool_event import TOOL_NAME
from grafi.common.events.tool_events.tool_event import TOOL_TYPE
from grafi.common.events.tool_events.tool_event import ToolEvent
from grafi.common.models.invoke_context import InvokeContext


@pytest.fixture
def tool_event() -> ToolEvent:
    return ToolEvent(
        event_id="test_id",
        event_type="ToolInvoke",
        timestamp="2009-02-13T23:31:30+00:00",
        tool_id="test_id",
        tool_name="test_tool",
        tool_type="test_type",
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
    )


@pytest.fixture
def tool_event_dict():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "ToolInvoke",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            TOOL_ID: "test_id",
            TOOL_NAME: "test_tool",
            TOOL_TYPE: "test_type",
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
    }


def test_tool_event_dict(tool_event: ToolEvent, tool_event_dict):
    assert tool_event.tool_event_dict() == tool_event_dict


def test_tool_event_base(tool_event_dict, tool_event):
    assert ToolEvent.tool_event_base(tool_event_dict) == tool_event
