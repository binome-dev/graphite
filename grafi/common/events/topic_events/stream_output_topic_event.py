from typing import Any
from typing import Dict
from typing import List
from typing import cast

from pydantic import ConfigDict

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.event import EventType
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import MsgsAGen


class StreamOutputTopicEvent(TopicEvent):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    consumed_event_ids: List[str] = []
    publisher_name: str
    publisher_type: str
    event_type: EventType = EventType.OUTPUT_TOPIC
    data: MsgsAGen

    def to_dict(self) -> Dict[str, Any]:
        # TODO: Implement serialization for `data` field
        event_context = {
            "consumed_event_ids": self.consumed_event_ids,
            "publisher_name": self.publisher_name,
            "publisher_type": self.publisher_type,
            "topic_name": self.topic_name,
            "offset": self.offset,
            "execution_context": self.execution_context.model_dump(),
        }

        return {
            **super().event_dict(),
            EVENT_CONTEXT: event_context,
            "data": None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StreamOutputTopicEvent":
        execution_context = ExecutionContext.model_validate(
            data[EVENT_CONTEXT]["execution_context"]
        )

        base_event = cls.event_base(data)

        return cls(
            event_id=base_event[0],
            event_type=base_event[1],
            timestamp=base_event[2],
            consumed_event_ids=data[EVENT_CONTEXT]["consumed_event_ids"],
            publisher_name=data[EVENT_CONTEXT]["publisher_name"],
            publisher_type=data[EVENT_CONTEXT]["publisher_type"],
            topic_name=data[EVENT_CONTEXT]["topic_name"],
            offset=data[EVENT_CONTEXT]["offset"],
            execution_context=execution_context,
            data=cast(MsgsAGen, None),
        )
