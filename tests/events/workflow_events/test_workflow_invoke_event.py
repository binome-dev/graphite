import pytest

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.workflow_events.workflow_event import WORKFLOW_ID
from grafi.common.events.workflow_events.workflow_event import WORKFLOW_NAME
from grafi.common.events.workflow_events.workflow_event import WORKFLOW_TYPE
from grafi.common.events.workflow_events.workflow_invoke_event import (
    WorkflowInvokeEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


@pytest.fixture
def workflow_invoke_event() -> WorkflowInvokeEvent:
    return WorkflowInvokeEvent(
        event_id="test_id",
        event_type="WorkflowInvoke",
        timestamp="2009-02-13T23:31:30+00:00",
        workflow_id="test_id",
        workflow_name="test_workflow",
        workflow_type="test_type",
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
def workflow_invoke_event_message() -> WorkflowInvokeEvent:
    return WorkflowInvokeEvent(
        event_id="test_id",
        event_type="WorkflowInvoke",
        timestamp="2009-02-13T23:31:30+00:00",
        workflow_id="test_id",
        workflow_name="test_workflow",
        workflow_type="test_type",
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
def workflow_invoke_event_dict():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "WorkflowInvoke",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            WORKFLOW_ID: "test_id",
            WORKFLOW_NAME: "test_workflow",
            WORKFLOW_TYPE: "test_type",
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": {
            "input_data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}]'
        },
    }


@pytest.fixture
def workflow_invoke_event_dict_message():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "WorkflowInvoke",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            WORKFLOW_ID: "test_id",
            WORKFLOW_NAME: "test_workflow",
            WORKFLOW_TYPE: "test_type",
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": {
            "input_data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}]'
        },
    }


def test_workflow_invoke_event_to_dict(
    workflow_invoke_event: WorkflowInvokeEvent, workflow_invoke_event_dict
):
    assert workflow_invoke_event.to_dict() == workflow_invoke_event_dict


def test_workflow_invoke_event_from_dict(
    workflow_invoke_event_dict, workflow_invoke_event
):
    assert (
        WorkflowInvokeEvent.from_dict(workflow_invoke_event_dict)
        == workflow_invoke_event
    )


def test_workflow_invoke_event_message_to_dict(
    workflow_invoke_event_message: WorkflowInvokeEvent,
    workflow_invoke_event_dict_message,
):
    assert workflow_invoke_event_message.to_dict() == workflow_invoke_event_dict_message


def test_workflow_invoke_event_message_from_dict(
    workflow_invoke_event_dict_message, workflow_invoke_event_message
):
    assert (
        WorkflowInvokeEvent.from_dict(workflow_invoke_event_dict_message)
        == workflow_invoke_event_message
    )
