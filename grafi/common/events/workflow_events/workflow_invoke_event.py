import json
from typing import Any
from typing import Dict

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from grafi.common.events.event import EventType
from grafi.common.events.workflow_events.workflow_event import WorkflowEvent
from grafi.common.models.message import Message
from grafi.common.models.message import Messages


class WorkflowInvokeEvent(WorkflowEvent):
    event_type: EventType = EventType.WORKFLOW_INVOKE
    input_data: Messages

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.workflow_event_dict(),
            "data": {
                "input_data": json.dumps(self.input_data, default=to_jsonable_python),
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowInvokeEvent":
        base_event = cls.workflow_event_base(data)
        input_data_dict = json.loads(data["data"]["input_data"])
        if isinstance(input_data_dict, list):
            input_data = TypeAdapter(Messages).validate_python(input_data_dict)
        else:
            input_data = [Message.model_validate(input_data_dict)]
        return cls(
            **base_event.model_dump(),
            input_data=input_data,
        )
