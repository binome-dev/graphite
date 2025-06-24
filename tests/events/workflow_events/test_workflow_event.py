import pytest

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.workflow_events.workflow_event import WORKFLOW_ID
from grafi.common.events.workflow_events.workflow_event import WORKFLOW_NAME
from grafi.common.events.workflow_events.workflow_event import WORKFLOW_TYPE
from grafi.common.events.workflow_events.workflow_event import WorkflowEvent
from grafi.common.models.invoke_context import InvokeContext


@pytest.fixture
def workflow_event() -> WorkflowEvent:
    return WorkflowEvent(
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
    )


@pytest.fixture
def workflow_event_dict():
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
    }


def test_workflow_event_dict(workflow_event: WorkflowEvent, workflow_event_dict):
    assert workflow_event.workflow_event_dict() == workflow_event_dict


def test_workflow_event_base(workflow_event_dict, workflow_event):
    assert WorkflowEvent.workflow_event_base(workflow_event_dict) == workflow_event
