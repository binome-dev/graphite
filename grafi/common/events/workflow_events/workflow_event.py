from typing import Any
from typing import Dict

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.event import Event
from grafi.common.models.default_id import default_id
from grafi.common.models.execution_context import ExecutionContext


WORKFLOW_ID = "workflow_id"
WORKFLOW_NAME = "workflow_name"
WORKFLOW_TYPE = "workflow_type"


class WorkflowEvent(Event):
    workflow_id: str = default_id
    workflow_name: str
    workflow_type: str

    def workflow_event_dict(self) -> Dict[str, Any]:
        event_context = {
            WORKFLOW_ID: self.workflow_id,
            WORKFLOW_NAME: self.workflow_name,
            WORKFLOW_TYPE: self.workflow_type,
            "execution_context": self.execution_context.model_dump(),
        }
        return {
            **self.event_dict(),
            EVENT_CONTEXT: event_context,
        }

    @classmethod
    def workflow_event_base(
        cls, workflow_event_dict: Dict[str, Any]
    ) -> "WorkflowEvent":
        workflow_id = workflow_event_dict[EVENT_CONTEXT][WORKFLOW_ID]
        workflow_name = workflow_event_dict[EVENT_CONTEXT][WORKFLOW_NAME]
        workflow_type = workflow_event_dict[EVENT_CONTEXT][WORKFLOW_TYPE]
        execution_context = ExecutionContext.model_validate(
            workflow_event_dict[EVENT_CONTEXT]["execution_context"]
        )
        event_base = cls.event_base(workflow_event_dict)
        return WorkflowEvent(
            event_id=event_base[0],
            event_type=event_base[1],
            timestamp=event_base[2],
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            workflow_type=workflow_type,
            execution_context=execution_context,
        )
