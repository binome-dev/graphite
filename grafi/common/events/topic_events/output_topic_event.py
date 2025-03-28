from typing import Any, AsyncGenerator, Dict, Generator, List, Union

from pydantic import ConfigDict

from grafi.common.events.event import EventType
from grafi.common.events.topic_events.publish_to_topic_event import (
    PublishToTopicEvent,
)
from grafi.common.models.message import Message


class OutputTopicEvent(PublishToTopicEvent):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    event_type: EventType = EventType.OUTPUT_TOPIC
    data: Union[
        Message,
        List[Message],
        Generator[Message, None, None],
        AsyncGenerator[Message, None],
    ]

    def to_dict(self):
        # TODO: Implement serialization for `data` field
        return {
            **super().to_dict(),
            "data": None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        # TODO: Implement deserialization for `data` field
        return cls(
            topic_name=data["topic_name"],
            node_name=data["node_name"],
            offset=data["offset"],
            data=None,
        )
