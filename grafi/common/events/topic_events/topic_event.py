from grafi.common.events.event import Event
from grafi.common.models.message import Messages
from grafi.common.topics.topic_types import TopicType


class TopicEvent(Event):
    topic_name: str
    topic_type: TopicType
    offset: int
    data: Messages
