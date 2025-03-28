import pytest

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.tool_events.tool_event import TOOL_ID, TOOL_NAME, TOOL_TYPE
from grafi.common.events.tool_events.tool_respond_event import ToolRespondEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message


@pytest.fixture
def tool_respond_event() -> ToolRespondEvent:
    return ToolRespondEvent(
        event_id="test_id",
        event_type="ToolRespond",
        timestamp="2009-02-13T23:31:30+00:00",
        tool_id="test_id",
        tool_name="test_tool",
        tool_type="test_type",
        execution_context=ExecutionContext(
            conversation_id="conversation_id",
            execution_id="execution_id",
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
        output_data=[
            Message(
                message_id="ea72df51439b42e4a43b217c9bca63f5",
                timestamp=1737138526189505000,
                role="user",
                content="Hello, my name is Grafi, how are you doing?",
                name=None,
                functions=None,
                function_call=None,
            ),
            Message(
                message_id="ea72df51439b42e4a43b217c9bca63f6",
                timestamp=1737138526189605000,
                role="assistant",
                content="Hello, Grafi, I am doing well, thank you.",
                name=None,
                functions=None,
                function_call=None,
            ),
        ],
    )


@pytest.fixture
def tool_respond_event_message() -> ToolRespondEvent:
    return ToolRespondEvent(
        event_id="test_id",
        event_type="ToolRespond",
        timestamp="2009-02-13T23:31:30+00:00",
        tool_id="test_id",
        tool_name="test_tool",
        tool_type="test_type",
        execution_context=ExecutionContext(
            conversation_id="conversation_id",
            execution_id="execution_id",
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
        output_data=Message(
            message_id="ea72df51439b42e4a43b217c9bca63f6",
            timestamp=1737138526189605000,
            role="assistant",
            content="Hello, Grafi, I am doing well, thank you.",
            name=None,
            functions=None,
            function_call=None,
        ),
    )


@pytest.fixture
def tool_respond_event_dict():
    return {
        "event_id": "test_id",
        "event_type": "ToolRespond",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            TOOL_ID: "test_id",
            TOOL_NAME: "test_tool",
            TOOL_TYPE: "test_type",
            "execution_context": {
                "conversation_id": "conversation_id",
                "execution_id": "execution_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": {
            "input_data": '[{"content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "role": "user", "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "tool_call_id": null, "tools": null, "functions": null}]',
            "output_data": '[{"content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "role": "user", "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "tool_call_id": null, "tools": null, "functions": null}, {"content": "Hello, Grafi, I am doing well, thank you.", "refusal": null, "role": "assistant", "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f6", "timestamp": 1737138526189605000, "tool_call_id": null, "tools": null, "functions": null}]',
        },
    }


@pytest.fixture
def tool_respond_event_dict_message():
    return {
        "event_id": "test_id",
        "event_type": "ToolRespond",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            TOOL_ID: "test_id",
            TOOL_NAME: "test_tool",
            TOOL_TYPE: "test_type",
            "execution_context": {
                "conversation_id": "conversation_id",
                "execution_id": "execution_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": {
            "input_data": '[{"content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "role": "user", "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "tool_call_id": null, "tools": null, "functions": null}]',
            "output_data": '{"content": "Hello, Grafi, I am doing well, thank you.", "refusal": null, "role": "assistant", "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f6", "timestamp": 1737138526189605000, "tool_call_id": null, "tools": null, "functions": null}',
        },
    }


def test_tool_respond_event_to_dict(
    tool_respond_event: ToolRespondEvent, tool_respond_event_dict
):
    assert tool_respond_event.to_dict() == tool_respond_event_dict


def test_tool_respond_event_from_dict(tool_respond_event_dict, tool_respond_event):
    assert ToolRespondEvent.from_dict(tool_respond_event_dict) == tool_respond_event


def test_tool_respond_event_message_to_dict(
    tool_respond_event_message: ToolRespondEvent, tool_respond_event_dict_message
):
    assert tool_respond_event_message.to_dict() == tool_respond_event_dict_message


def test_tool_respond_event_message_from_dict(
    tool_respond_event_dict_message, tool_respond_event_message
):
    assert (
        ToolRespondEvent.from_dict(tool_respond_event_dict_message)
        == tool_respond_event_message
    )
