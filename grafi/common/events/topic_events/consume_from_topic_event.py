from grafi.common.events.event import EventType
from grafi.common.events.topic_events.topic_event import TopicEvent


class ConsumeFromTopicEvent(TopicEvent):
    event_type: EventType = EventType.CONSUME_FROM_TOPIC
    consumer_name: str = ""
    consumer_type: str = ""
