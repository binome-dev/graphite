from typing import Any

import pytest

from grafi.common.events.component_events import ToolInvokeEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


@pytest.fixture
def tool_invoke_event() -> Any:
    return ToolInvokeEvent(
        event_id="test_id",
        event_type="ToolInvoke",
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
    )


@pytest.fixture
def tool_invoke_event_message() -> Any:
    return ToolInvokeEvent(
        event_id="test_id",
        event_type="ToolInvoke",
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
    )


@pytest.fixture
def tool_invoke_event_dict():
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
                    "is_streaming": False,
                }
            ]
        },
    }


@pytest.fixture
def tool_invoke_event_dict_message():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "ToolInvoke",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
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
            ]
        },
    }


def test_tool_invoke_event_to_dict(tool_invoke_event, tool_invoke_event_dict):
    assert tool_invoke_event.to_dict() == tool_invoke_event_dict


def test_tool_invoke_event_from_dict(tool_invoke_event_dict, tool_invoke_event):
    assert ToolInvokeEvent.from_dict(tool_invoke_event_dict) == tool_invoke_event


def test_tool_invoke_event_message_to_dict(
    tool_invoke_event_message, tool_invoke_event_dict_message
):
    assert tool_invoke_event_message.to_dict() == tool_invoke_event_dict_message


def test_tool_invoke_event_message_from_dict(
    tool_invoke_event_dict_message, tool_invoke_event_message
):
    assert (
        ToolInvokeEvent.from_dict(tool_invoke_event_dict_message)
        == tool_invoke_event_message
    )
