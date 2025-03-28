from typing import Any, Dict, List

from grafi.common.events.event import EventType
from grafi.common.events.topic_events.topic_event import TopicEvent


class PublishToTopicEvent(TopicEvent):
    consumed_event_ids: List[str] = []
    publisher_name: str
    publisher_type: str
    event_type: EventType = EventType.PUBLISH_TO_TOPIC

    def to_dict(self):
        return {
            "consumed_event_ids": self.consumed_event_ids,
            "publisher_name": self.publisher_name,
            "publisher_type": self.publisher_type,
            **super().topic_event_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        base_event = cls.topic_event_base(data)
        return cls(
            consumed_event_ids=data["consumed_event_ids"],
            publisher_name=data["publisher_name"],
            publisher_type=data["publisher_type"],
            **base_event.model_dump(),
        )
