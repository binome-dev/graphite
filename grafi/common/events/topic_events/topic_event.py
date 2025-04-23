from typing import Any

from grafi.common.events.event import Event


class TopicEvent(Event):
    topic_name: str
    offset: int
    data: Any
