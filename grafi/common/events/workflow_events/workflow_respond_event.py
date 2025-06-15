"""Module for handling workflow response events in the workflow system."""

import json
from typing import Any
from typing import Dict

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from grafi.common.events.event import EventType
from grafi.common.events.workflow_events.workflow_event import WorkflowEvent
from grafi.common.models.message import Messages


class WorkflowRespondEvent(WorkflowEvent):
    """Represents a workflow response event in the workflow system."""

    event_type: EventType = EventType.WORKFLOW_RESPOND
    input_data: Messages
    output_data: Messages

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.workflow_event_dict(),
            "data": {
                "input_data": json.dumps(self.input_data, default=to_jsonable_python),
                "output_data": json.dumps(self.output_data, default=to_jsonable_python),
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowRespondEvent":
        base_event = cls.workflow_event_base(data)
        input_data_dict = json.loads(data["data"]["input_data"])
        return cls(
            **base_event.model_dump(),
            input_data=TypeAdapter(Messages).validate_python(input_data_dict),
            output_data=TypeAdapter(Messages).validate_python(
                json.loads(data["data"]["output_data"])
            ),
        )
