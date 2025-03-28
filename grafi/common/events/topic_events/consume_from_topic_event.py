from grafi.common.events.event import EventType
from grafi.common.events.topic_events.topic_event import TopicEvent


class ConsumeFromTopicEvent(TopicEvent):
    event_type: EventType = EventType.CONSUME_FROM_TOPIC
    consumer_name: str
    consumer_type: str

    def to_dict(self):
        return {
            "consumer_name": self.consumer_name,
            "consumer_type": self.consumer_type,
            **super().topic_event_dict(),
        }

    @classmethod
    def from_dict(cls, data):
        base_event = cls.topic_event_base(data)
        return cls(
            consumer_name=data["consumer_name"],
            consumer_type=data["consumer_type"],
            **base_event.model_dump(),
        )
