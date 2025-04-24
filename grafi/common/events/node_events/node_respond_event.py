"""Module for handling node response events in the workflow system."""

import json
from typing import Any
from typing import Dict
from typing import List

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from grafi.common.events.event import EventType
from grafi.common.events.node_events.node_event import NodeEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.message import Messages


class NodeRespondEvent(NodeEvent):
    """Represents a node response event in the workflow system."""

    event_type: EventType = EventType.NODE_RESPOND
    input_data: List[ConsumeFromTopicEvent]
    output_data: Messages

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.node_event_dict(),
            "data": {
                "input_data": [event.to_dict() for event in self.input_data],
                "output_data": json.dumps(self.output_data, default=to_jsonable_python),
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeRespondEvent":
        base_event = cls.node_event_base(data)
        return cls(
            **base_event.model_dump(),
            input_data=[
                ConsumeFromTopicEvent.from_dict(event)
                for event in data["data"]["input_data"]
            ],
            output_data=TypeAdapter(Messages).validate_python(
                json.loads(data["data"]["output_data"])
            ),
        )
