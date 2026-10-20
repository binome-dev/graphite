from grafi.common.events.event import Event
from grafi.common.events.event import EventType
from grafi.common.models.message import Messages
from grafi.topics.topic_types import TopicType


class TopicEvent(Event):
    event_type: EventType = EventType.TOPIC_EVENT
    name: str = ""
    type: TopicType = TopicType.NONE_TOPIC_TYPE
    offset: int = -1
    data: Messages
