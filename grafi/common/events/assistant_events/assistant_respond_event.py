from typing import Any, List
from typing import Dict


from grafi.common.events.assistant_events.assistant_event import AssistantEvent
from grafi.common.events.event import EventType
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent


class AssistantRespondEvent(AssistantEvent):
    event_type: EventType = EventType.ASSISTANT_RESPOND
    input_event: PublishToTopicEvent
    output_data: List[ConsumeFromTopicEvent]

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.assistant_event_dict(),
            "data": {
                "input_event": self.input_event.to_dict(),
                "output_data": [event.to_dict() for event in self.output_data],
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssistantRespondEvent":
        base_event = cls.assistant_event_base(data)
        return cls(
            **base_event.model_dump(),
            input_event=PublishToTopicEvent.from_dict(data["data"]["input_event"]),
            output_data=[
                ConsumeFromTopicEvent.from_dict(event)
                for event in data["data"]["output_data"]
            ],
        )
