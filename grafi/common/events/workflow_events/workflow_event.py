from typing import Any
from typing import Dict

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.event import Event
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext


class WorkflowEvent(Event):
    id: str = default_id
    name: str
    type: str

    def workflow_event_dict(self) -> Dict[str, Any]:
        event_context = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "invoke_context": self.invoke_context.model_dump(),
        }
        return {
            **self.event_dict(),
            EVENT_CONTEXT: event_context,
        }

    @classmethod
    def workflow_event_base(
        cls, workflow_event_dict: Dict[str, Any]
    ) -> "WorkflowEvent":
        id = workflow_event_dict[EVENT_CONTEXT]["id"]
        name = workflow_event_dict[EVENT_CONTEXT]["name"]
        type = workflow_event_dict[EVENT_CONTEXT]["type"]
        invoke_context = InvokeContext.model_validate(
            workflow_event_dict[EVENT_CONTEXT]["invoke_context"]
        )
        event_base = cls.event_base(workflow_event_dict)
        return WorkflowEvent(
            event_id=event_base[0],
            event_type=event_base[1],
            timestamp=event_base[2],
            id=id,
            name=name,
            type=type,
            invoke_context=invoke_context,
        )
