from grafi.common.events.event import Event


class TopicEvent(Event):
    topic_name: str
    offset: int
