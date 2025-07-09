from typing import List

from pydantic import ConfigDict

from grafi.common.events.event import EventType
from grafi.common.events.topic_events.topic_event import TopicEvent


class OutputAsyncEvent(TopicEvent):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    consumed_event_ids: List[str] = []
    publisher_name: str
    publisher_type: str
    event_type: EventType = EventType.OUTPUT_TOPIC
