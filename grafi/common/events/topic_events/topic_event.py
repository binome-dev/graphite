from grafi.common.events.event import Event
from grafi.common.models.message import Messages
from grafi.topics.topic_types import TopicType


class TopicEvent(Event):
    name: str = ""
    type: TopicType = TopicType.NONE_TOPIC_TYPE
    offset: int = -1
    data: Messages
