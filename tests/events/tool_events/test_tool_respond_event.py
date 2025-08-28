import pytest

from grafi.common.events.component_events import ToolRespondEvent
from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


@pytest.fixture
def tool_respond_event() -> ToolRespondEvent:
    return ToolRespondEvent(
        event_id="test_id",
        event_type="ToolRespond",
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
        output_data=[
            Message(
                message_id="ea72df51439b42e4a43b217c9bca63f6",
                timestamp=1737138526189605000,
                role="assistant",
                content="Hello, Grafi, I am doing well, thank you.",
                name=None,
                functions=None,
                function_call=None,
            )
        ],
    )


@pytest.fixture
def tool_respond_event_dict():
    return {
        "event_id": "test_id",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "ToolRespond",
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
            "output_data": [
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
                },
                {
                    "name": None,
                    "message_id": "ea72df51439b42e4a43b217c9bca63f6",
                    "timestamp": 1737138526189605000,
                    "content": "Hello, Grafi, I am doing well, thank you.",
                    "refusal": None,
                    "annotations": None,
                    "audio": None,
                    "role": "assistant",
                    "tool_call_id": None,
                    "tools": None,
                    "function_call": None,
                    "tool_calls": None,
                    "is_streaming": False,
                },
            ],
        },
    }


@pytest.fixture
def tool_respond_event_dict_message():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "ToolRespond",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            "id": "test_id",
            "name": "test_tool",
            "type": "test_type",
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "kwargs": {},
                "user_id": "",
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
            "output_data": [
                {
                    "name": None,
                    "message_id": "ea72df51439b42e4a43b217c9bca63f6",
                    "timestamp": 1737138526189605000,
                    "content": "Hello, Grafi, I am doing well, thank you.",
                    "refusal": None,
                    "annotations": None,
                    "audio": None,
                    "role": "assistant",
                    "tool_call_id": None,
                    "tools": None,
                    "function_call": None,
                    "tool_calls": None,
                    "is_streaming": False,
                },
            ],
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
