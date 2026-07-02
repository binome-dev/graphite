import json
from typing import Any
from typing import Dict
from typing import List

from pydantic import Field
from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.event import EventType
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.topics.topic_types import TopicType


class ConsumeFromTopicEvent(TopicEvent):
    event_type: EventType = EventType.CONSUME_FROM_TOPIC
    consumer_name: str = ""
    consumer_type: str = ""
    # The publish events this consumed batch derives from. Propagated from the
    # source PublishToTopicEvent so a node can resolve a HITL resume reply back
    # to the recorded review event it approves (recover-from-store, D11).
    consumed_event_ids: List[str] = Field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        event_context = {
            "consumer_name": self.consumer_name,
            "consumer_type": self.consumer_type,
            "name": self.name,
            "type": self.type.value,
            "offset": self.offset,
            "consumed_event_ids": self.consumed_event_ids,
            "invoke_context": self.invoke_context.model_dump(),
        }

        return {
            EVENT_CONTEXT: event_context,
            **super().event_dict(),
            "data": json.dumps(self.data, default=to_jsonable_python),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConsumeFromTopicEvent":
        invoke_context = InvokeContext.model_validate(
            data[EVENT_CONTEXT]["invoke_context"]
        )

        data_dict = json.loads(data["data"])

        data_obj = TypeAdapter(Messages).validate_python(data_dict)

        base_event = cls.event_base(data)
        return cls(
            **base_event,
            consumer_name=data[EVENT_CONTEXT]["consumer_name"],
            consumer_type=data[EVENT_CONTEXT]["consumer_type"],
            name=data[EVENT_CONTEXT]["name"],
            type=TopicType(data[EVENT_CONTEXT]["type"]),
            offset=data[EVENT_CONTEXT]["offset"],
            consumed_event_ids=data[EVENT_CONTEXT].get("consumed_event_ids", []),
            invoke_context=invoke_context,
            data=data_obj,
        )
