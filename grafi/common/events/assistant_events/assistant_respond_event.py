import json
from typing import Any, List
from typing import Dict

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from grafi.common.events.assistant_events.assistant_event import AssistantEvent
from grafi.common.events.event import EventType
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.message import Messages


class AssistantRespondEvent(AssistantEvent):
    event_type: EventType = EventType.ASSISTANT_RESPOND
    input_data: Messages
    output_data: List[ConsumeFromTopicEvent]

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.assistant_event_dict(),
            "data": {
                "input_data": json.dumps(self.input_data, default=to_jsonable_python),
                "output_data": json.dumps(self.output_data, default=to_jsonable_python),
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssistantRespondEvent":
        base_event = cls.assistant_event_base(data)
        return cls(
            **base_event.model_dump(),
            input_data=TypeAdapter(Messages).validate_python(
                json.loads(data["data"]["input_data"])
            ),
            output_data=TypeAdapter(List[ConsumeFromTopicEvent]).validate_python(
                json.loads(data["data"]["output_data"])
            ),
        )
