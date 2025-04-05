import pytest

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.workflow_events.workflow_event import (
    WORKFLOW_ID,
    WORKFLOW_NAME,
    WORKFLOW_TYPE,
)
from grafi.common.events.workflow_events.workflow_failed_event import (
    WorkflowFailedEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message


@pytest.fixture
def workflow_failed_event() -> WorkflowFailedEvent:
    return WorkflowFailedEvent(
        event_id="test_id",
        event_type="WorkflowFailed",
        timestamp="2009-02-13T23:31:30+00:00",
        workflow_id="test_id",
        workflow_name="test_workflow",
        workflow_type="test_type",
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
        error="error",
    )


@pytest.fixture
def workflow_failed_event_dict():
    return {
        "event_id": "test_id",
        "event_type": "WorkflowFailed",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            WORKFLOW_ID: "test_id",
            WORKFLOW_NAME: "test_workflow",
            WORKFLOW_TYPE: "test_type",
            "execution_context": {
                "conversation_id": "conversation_id",
                "execution_id": "execution_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": {
            "input_data": '[{"content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "role": "user", "annotations": null, "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "tool_call_id": null, "tools": null, "functions": null}]',
            "error": "error",
        },
    }


def test_workflow_failed_event_to_dict(
    workflow_failed_event: WorkflowFailedEvent, workflow_failed_event_dict
):
    assert workflow_failed_event.to_dict() == workflow_failed_event_dict


def test_workflow_failed_event_from_dict(
    workflow_failed_event_dict, workflow_failed_event
):
    assert (
        WorkflowFailedEvent.from_dict(workflow_failed_event_dict)
        == workflow_failed_event
    )
