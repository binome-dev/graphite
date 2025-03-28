import json
from typing import Any, AsyncGenerator, Dict, List, Union

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from grafi.common.events.event import EVENT_CONTEXT, Event
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message


class TopicEvent(Event):
    topic_name: str
    offset: int
    data: Union[Message, List[Message], AsyncGenerator[Message, None]]

    def topic_event_dict(self):
        event_context = {
            "topic_name": self.topic_name,
            "offset": self.offset,
            "execution_context": self.execution_context.model_dump(),
        }
        return {
            **self.event_dict(),
            EVENT_CONTEXT: event_context,
            "data": json.dumps(self.data, default=to_jsonable_python),
        }

    @classmethod
    def topic_event_base(cls, topic_event_dict: Dict[str, Any]) -> "TopicEvent":
        execution_context = ExecutionContext.model_validate(
            topic_event_dict[EVENT_CONTEXT]["execution_context"]
        )
        event_base = cls.event_base(topic_event_dict)

        data_dict = json.loads(topic_event_dict["data"])
        if isinstance(data_dict, list):
            data = TypeAdapter(List[Message]).validate_python(data_dict)
        else:
            data = Message.model_validate(data_dict)

        return TopicEvent(
            event_id=event_base[0],
            event_type=event_base[1],
            timestamp=event_base[2],
            topic_name=topic_event_dict[EVENT_CONTEXT]["topic_name"],
            offset=topic_event_dict[EVENT_CONTEXT]["offset"],
            execution_context=execution_context,
            data=data,
        )
