from grafi.common.events.event import Event
from grafi.common.models.message import Messages


class TopicEvent(Event):
    topic_name: str
    offset: int
    data: Messages
