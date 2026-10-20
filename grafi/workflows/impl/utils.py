from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.topic_event import TopicEvent


def consumption_of(
    event: TopicEvent, consumer_name: str, consumer_type: str
) -> ConsumeFromTopicEvent:
    """The record of a consumer taking ``event`` from its topic."""
    return ConsumeFromTopicEvent(
        name=event.name,
        type=event.type,
        consumer_name=consumer_name,
        consumer_type=consumer_type,
        invoke_context=event.invoke_context,
        offset=event.offset,
        data=event.data,
    )
