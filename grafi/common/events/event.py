from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Tuple

from pydantic import BaseModel, ConfigDict, Field

from grafi.common.models.default_id import default_id
from grafi.common.models.event_id import EventId
from grafi.common.models.execution_context import ExecutionContext


class EventType(Enum):
    NODE_INVOKE = "NodeInvoke"
    NODE_RESPOND = "NodeRespond"
    NODE_FAILED = "NodeFailed"
    TOOL_INVOKE = "ToolInvoke"
    TOOL_RESPOND = "ToolRespond"
    TOOL_FAILED = "ToolFailed"
    WORKFLOW_INVOKE = "WorkflowInvoke"
    WORKFLOW_RESPOND = "WorkflowRespond"
    WORKFLOW_FAILED = "WorkflowFailed"
    ASSISTANT_INVOKE = "AssistantInvoke"
    ASSISTANT_RESPOND = "AssistantRespond"
    ASSISTANT_FAILED = "AssistantFailed"

    TOPIC_EVENT = "TopicEvent"
    STREAM_TOPIC_EVENT = "StreamTopicEvent"
    PUBLISH_TO_TOPIC = "PublishToTopic"
    CONSUME_FROM_TOPIC = "ConsumeFromTopic"
    OUTPUT_TOPIC = "OutputTopic"


EVENT_CONTEXT = "event_context"


class Event(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    event_id: EventId = default_id
    execution_context: ExecutionContext
    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def event_dict(self, *args, **kwargs):
        # Flatten `execution_context` fields into the root level
        base_dict = {
            "event_id": self.event_id,
            "assistant_request_id": self.execution_context.assistant_request_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
        }
        return base_dict

    @classmethod
    def event_base(cls, event_dict: dict) -> Tuple[str, EventType, datetime]:
        event_id = event_dict["event_id"]
        event_type = EventType(event_dict["event_type"])
        timestamp = datetime.fromisoformat(event_dict["timestamp"])

        return event_id, event_type, timestamp

    def to_dict(self) -> Dict[str, Any]:
        # Return a dictionary representation of the event
        raise NotImplementedError

    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        # Return an event object from a dictionary
        raise NotImplementedError
