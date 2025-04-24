from typing import Any
from typing import Dict
from typing import cast

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.event import EventType
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import MsgsAGen


class ConsumeFromStreamTopicEvent(TopicEvent):
    event_type: EventType = EventType.CONSUME_FROM_TOPIC
    consumer_name: str
    consumer_type: str
    data: MsgsAGen

    def to_dict(self) -> Dict[str, Any]:
        event_context = {
            "consumer_name": self.consumer_name,
            "consumer_type": self.consumer_type,
            "topic_name": self.topic_name,
            "offset": self.offset,
            "execution_context": self.execution_context.model_dump(),
        }

        return {
            EVENT_CONTEXT: event_context,
            **super().event_dict(),
            "data": None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConsumeFromStreamTopicEvent":
        execution_context = ExecutionContext.model_validate(
            data[EVENT_CONTEXT]["execution_context"]
        )

        base_event = cls.event_base(data)
        return cls(
            event_id=base_event[0],
            event_type=base_event[1],
            timestamp=base_event[2],
            consumer_name=data[EVENT_CONTEXT]["consumer_name"],
            consumer_type=data[EVENT_CONTEXT]["consumer_type"],
            topic_name=data[EVENT_CONTEXT]["topic_name"],
            offset=data[EVENT_CONTEXT]["offset"],
            execution_context=execution_context,
            data=cast(MsgsAGen, None),
        )
