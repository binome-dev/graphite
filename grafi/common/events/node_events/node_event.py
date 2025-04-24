from typing import Any
from typing import Dict
from typing import List

from pydantic import Field

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.event import Event
from grafi.common.models.default_id import default_id
from grafi.common.models.execution_context import ExecutionContext


NODE_ID = "node_id"
NODE_NAME = "node_name"
NODE_TYPE = "node_type"
SUBSCRIBED_TOPICS = "subscribed_topics"
PUBLISH_TO_TOPICS = "publish_to_topics"


class NodeEvent(Event):
    node_id: str = default_id
    subscribed_topics: List[str] = Field(default_factory=list)
    publish_to_topics: List[str] = Field(default_factory=list)
    node_name: str
    node_type: str

    def node_event_dict(self) -> Dict[str, Any]:
        event_context = {
            NODE_ID: self.node_id,
            SUBSCRIBED_TOPICS: self.subscribed_topics,
            PUBLISH_TO_TOPICS: self.publish_to_topics,
            NODE_NAME: self.node_name,
            NODE_TYPE: self.node_type,
            "execution_context": self.execution_context.model_dump(),
        }
        return {
            **self.event_dict(),
            EVENT_CONTEXT: event_context,
        }

    @classmethod
    def node_event_base(cls, node_event_dict: Dict[str, Any]) -> "NodeEvent":
        node_id = node_event_dict[EVENT_CONTEXT][NODE_ID]
        subscribed_topics = node_event_dict[EVENT_CONTEXT][SUBSCRIBED_TOPICS]
        publish_to_topics = node_event_dict[EVENT_CONTEXT][PUBLISH_TO_TOPICS]
        node_name = node_event_dict[EVENT_CONTEXT][NODE_NAME]
        node_type = node_event_dict[EVENT_CONTEXT][NODE_TYPE]
        execution_context = ExecutionContext.model_validate(
            node_event_dict[EVENT_CONTEXT]["execution_context"]
        )
        event_base = cls.event_base(node_event_dict)
        return NodeEvent(
            event_id=event_base[0],
            event_type=event_base[1],
            timestamp=event_base[2],
            node_id=node_id,
            subscribed_topics=subscribed_topics,
            publish_to_topics=publish_to_topics,
            node_name=node_name,
            node_type=node_type,
            execution_context=execution_context,
        )
