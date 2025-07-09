import json
from typing import Any
from typing import Dict
from typing import List

from pydantic import ConfigDict
from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.event import EventType
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages


class OutputTopicEvent(TopicEvent):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    consumed_event_ids: List[str] = []
    publisher_name: str
    publisher_type: str
    event_type: EventType = EventType.OUTPUT_TOPIC

    def to_dict(self) -> Dict[str, Any]:
        # TODO: Implement serialization for `data` field
        event_context = {
            "consumed_event_ids": self.consumed_event_ids,
            "publisher_name": self.publisher_name,
            "publisher_type": self.publisher_type,
            "topic_name": self.topic_name,
            "offset": self.offset,
            "invoke_context": self.invoke_context.model_dump(),
        }

        return {
            **super().event_dict(),
            EVENT_CONTEXT: event_context,
            "data": json.dumps(self.data, default=to_jsonable_python),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutputTopicEvent":
        invoke_context = InvokeContext.model_validate(
            data[EVENT_CONTEXT]["invoke_context"]
        )

        data_dict = json.loads(data["data"])
        base_event = cls.event_base(data)

        if isinstance(data_dict, list):
            data_obj = TypeAdapter(Messages).validate_python(data_dict)
        else:
            data_obj = [Message.model_validate(data_dict)]

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
            invoke_context=invoke_context,
            data=data_obj,
        )
