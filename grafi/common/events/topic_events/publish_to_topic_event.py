import json
from typing import Any, Dict, List, Union

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from grafi.common.events.event import EVENT_CONTEXT, EventType
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message


class PublishToTopicEvent(TopicEvent):
    consumed_event_ids: List[str] = []
    publisher_name: str
    publisher_type: str
    event_type: EventType = EventType.PUBLISH_TO_TOPIC

    data: Union[Message, List[Message]]

    def to_dict(self):

        event_context = {
            "consumed_event_ids": self.consumed_event_ids,
            "publisher_name": self.publisher_name,
            "publisher_type": self.publisher_type,
            "topic_name": self.topic_name,
            "offset": self.offset,
            "execution_context": self.execution_context.model_dump(),
        }

        return {
            EVENT_CONTEXT: event_context,
            **super().event_dict(),
            "data": json.dumps(self.data, default=to_jsonable_python),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        execution_context = ExecutionContext.model_validate(
            data[EVENT_CONTEXT]["execution_context"]
        )

        data_dict = json.loads(data["data"])
        if isinstance(data_dict, list):
            data_obj = TypeAdapter(List[Message]).validate_python(data_dict)
        else:
            data_obj = Message.model_validate(data_dict)

        base_event = cls.event_base(data)
        return cls(
            event_id=base_event[0],
            event_type=base_event[1],
            timestamp=base_event[2],
            consumed_event_ids=data[EVENT_CONTEXT]["consumed_event_ids"],
            publisher_name=data[EVENT_CONTEXT]["publisher_name"],
            publisher_type=data[EVENT_CONTEXT]["publisher_type"],
            topic_name=data[EVENT_CONTEXT]["topic_name"],
            offset=data[EVENT_CONTEXT]["offset"],
            execution_context=execution_context,
            data=data_obj,
        )
