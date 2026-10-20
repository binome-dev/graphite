"""The events of a component's lifecycle: a node, tool, workflow or
assistant being invoked, responding, or failing. Each class fixes its
``event_type``, and holds what its component took and gave."""

from typing import List
from typing import Optional

from grafi.common.events.component_base import AssistantEventBase
from grafi.common.events.component_base import FailedEvent
from grafi.common.events.component_base import InvokeEvent
from grafi.common.events.component_base import NodeEventBase
from grafi.common.events.component_base import RespondEvent
from grafi.common.events.component_base import ToolEventBase
from grafi.common.events.component_base import WorkflowEventBase
from grafi.common.events.event import EventType
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.message import Messages

# A node takes the events it consumed, and gives one publication, or none.


class NodeInvokeEvent(InvokeEvent[List[ConsumeFromTopicEvent]], NodeEventBase):
    event_type: EventType = EventType.NODE_INVOKE


class NodeRespondEvent(
    RespondEvent[List[ConsumeFromTopicEvent], Optional[PublishToTopicEvent]],
    NodeEventBase,
):
    event_type: EventType = EventType.NODE_RESPOND


class NodeFailedEvent(FailedEvent[List[ConsumeFromTopicEvent]], NodeEventBase):
    event_type: EventType = EventType.NODE_FAILED


# A tool takes messages, and gives messages.


class ToolInvokeEvent(InvokeEvent[Messages], ToolEventBase):
    event_type: EventType = EventType.TOOL_INVOKE


class ToolRespondEvent(RespondEvent[Messages, Messages], ToolEventBase):
    event_type: EventType = EventType.TOOL_RESPOND


class ToolFailedEvent(FailedEvent[Messages], ToolEventBase):
    event_type: EventType = EventType.TOOL_FAILED


# A workflow, and an assistant, take one publication, and give the events
# consumed from their output topics.


class WorkflowInvokeEvent(InvokeEvent[PublishToTopicEvent], WorkflowEventBase):
    event_type: EventType = EventType.WORKFLOW_INVOKE


class WorkflowRespondEvent(
    RespondEvent[PublishToTopicEvent, List[ConsumeFromTopicEvent]], WorkflowEventBase
):
    event_type: EventType = EventType.WORKFLOW_RESPOND


class WorkflowFailedEvent(FailedEvent[PublishToTopicEvent], WorkflowEventBase):
    event_type: EventType = EventType.WORKFLOW_FAILED


class AssistantInvokeEvent(InvokeEvent[PublishToTopicEvent], AssistantEventBase):
    event_type: EventType = EventType.ASSISTANT_INVOKE


class AssistantRespondEvent(
    RespondEvent[PublishToTopicEvent, List[ConsumeFromTopicEvent]],
    AssistantEventBase,
):
    event_type: EventType = EventType.ASSISTANT_RESPOND


class AssistantFailedEvent(FailedEvent[PublishToTopicEvent], AssistantEventBase):
    event_type: EventType = EventType.ASSISTANT_FAILED


__all__ = [
    "NodeInvokeEvent",
    "NodeRespondEvent",
    "NodeFailedEvent",
    "ToolInvokeEvent",
    "ToolRespondEvent",
    "ToolFailedEvent",
    "WorkflowInvokeEvent",
    "WorkflowRespondEvent",
    "WorkflowFailedEvent",
    "AssistantInvokeEvent",
    "AssistantRespondEvent",
    "AssistantFailedEvent",
]
