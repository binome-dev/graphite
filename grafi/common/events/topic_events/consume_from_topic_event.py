import json
from typing import Any, AsyncGenerator, Dict, List, Union

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from grafi.common.events.event import EVENT_CONTEXT, EventType
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message


class ConsumeFromTopicEvent(TopicEvent):
    event_type: EventType = EventType.CONSUME_FROM_TOPIC
    consumer_name: str
    consumer_type: str
    data: Union[Message, List[Message], AsyncGenerator[Message, None]]

    def to_dict(self):

        event_context = {
            "consumer_name": self.consumer_name,
            "consumer_type": self.consumer_type,
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
            consumer_name=data[EVENT_CONTEXT]["consumer_name"],
            consumer_type=data[EVENT_CONTEXT]["consumer_type"],
            topic_name=data[EVENT_CONTEXT]["topic_name"],
            offset=data[EVENT_CONTEXT]["offset"],
            execution_context=execution_context,
            data=data_obj,
        )
