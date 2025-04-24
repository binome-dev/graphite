import json
from typing import Any
from typing import Dict

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from grafi.common.events.event import EventType
from grafi.common.events.tool_events.tool_event import ToolEvent
from grafi.common.models.message import Message
from grafi.common.models.message import Messages


class ToolRespondEvent(ToolEvent):
    event_type: EventType = EventType.TOOL_RESPOND
    input_data: Messages
    output_data: Messages

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.tool_event_dict(),
            "data": {
                "input_data": json.dumps(self.input_data, default=to_jsonable_python),
                "output_data": json.dumps(self.output_data, default=to_jsonable_python),
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolRespondEvent":
        base_event = cls.tool_event_base(data)
        input_data_dict = json.loads(data["data"]["input_data"])
        if isinstance(input_data_dict, list):
            input_data = TypeAdapter(Messages).validate_python(
                json.loads(data["data"]["input_data"])
            )
        else:
            input_data = [Message.model_validate(input_data_dict)]

        output_data_dict = json.loads(data["data"]["output_data"])
        if isinstance(output_data_dict, list):
            output_data = TypeAdapter(Messages).validate_python(
                json.loads(data["data"]["output_data"])
            )
        else:
            output_data = [Message.model_validate(output_data_dict)]

        return cls(
            **base_event.model_dump(),
            input_data=input_data,
            output_data=output_data,
        )
