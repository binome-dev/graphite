from typing import Any
from typing import Dict
from typing import List

from pydantic import Field

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.event import Event
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext


class NodeEvent(Event):
    id: str = default_id
    subscribed_topics: List[str] = Field(default_factory=list)
    publish_to_topics: List[str] = Field(default_factory=list)
    name: str
    type: str

    def node_event_dict(self) -> Dict[str, Any]:
        event_context = {
            "id": self.id,
            "subscribed_topics": self.subscribed_topics,
            "publish_to_topics": self.publish_to_topics,
            "name": self.name,
            "type": self.type,
            "invoke_context": self.invoke_context.model_dump(),
        }
        return {
            **self.event_dict(),
            EVENT_CONTEXT: event_context,
        }

    @classmethod
    def node_event_base(cls, node_event_dict: Dict[str, Any]) -> "NodeEvent":
        id = node_event_dict[EVENT_CONTEXT]["id"]
        subscribed_topics = node_event_dict[EVENT_CONTEXT]["subscribed_topics"]
        publish_to_topics = node_event_dict[EVENT_CONTEXT]["publish_to_topics"]
        name = node_event_dict[EVENT_CONTEXT]["name"]
        type = node_event_dict[EVENT_CONTEXT]["type"]
        invoke_context = InvokeContext.model_validate(
            node_event_dict[EVENT_CONTEXT]["invoke_context"]
        )
        event_base = cls.event_base(node_event_dict)
        return NodeEvent(
            event_id=event_base[0],
            event_type=event_base[1],
            timestamp=event_base[2],
            id=id,
            subscribed_topics=subscribed_topics,
            publish_to_topics=publish_to_topics,
            name=name,
            type=type,
            invoke_context=invoke_context,
        )
