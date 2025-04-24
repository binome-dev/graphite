import json
from typing import Any
from typing import Dict

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from grafi.common.events.assistant_events.assistant_event import AssistantEvent
from grafi.common.events.event import EventType
from grafi.common.models.message import Messages


class AssistantFailedEvent(AssistantEvent):
    event_type: EventType = EventType.ASSISTANT_FAILED
    input_data: Messages
    error: Any

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.assistant_event_dict(),
            "data": {
                "input_data": json.dumps(self.input_data, default=to_jsonable_python),
                "error": self.error,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssistantFailedEvent":
        base_event = cls.assistant_event_base(data)
        return cls(
            **base_event.model_dump(),
            input_data=TypeAdapter(Messages).validate_python(
                json.loads(data["data"]["input_data"])
            ),
            error=data["data"]["error"],
        )
