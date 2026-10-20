from typing import List
from typing import Optional

from grafi.common.events.event import EventType
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.event_id import EventId


class PublishToTopicEvent(TopicEvent):
    # The immediate source emission; event_id identifies this destination's publication.
    emission_id: Optional[EventId] = None
    consumed_event_ids: List[str] = []
    publisher_name: str = ""
    publisher_type: str = ""
    event_type: EventType = EventType.PUBLISH_TO_TOPIC
