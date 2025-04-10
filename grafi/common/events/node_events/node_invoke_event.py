from typing import Any
from typing import Dict
from typing import List

from grafi.common.events.event import EventType
from grafi.common.events.node_events.node_event import NodeEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)


class NodeInvokeEvent(NodeEvent):
    event_type: EventType = EventType.NODE_INVOKE
    input_data: List[ConsumeFromTopicEvent]

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.node_event_dict(),
            "data": {
                "input_data": [event.to_dict() for event in self.input_data],
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeInvokeEvent":
        base_event = cls.node_event_base(data)
        return cls(
            **base_event.model_dump(),
            input_data=[
                ConsumeFromTopicEvent.from_dict(event)
                for event in data["data"]["input_data"]
            ],
        )
