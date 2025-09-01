"""
Simplified event implementations using the base event framework.
This module replaces 20+ separate event files with a single, maintainable module.
"""

from typing import Any
from typing import Dict
from typing import List

from grafi.common.events.component_base import AssistantEventBase
from grafi.common.events.component_base import NodeEventBase
from grafi.common.events.component_base import ToolEventBase
from grafi.common.events.component_base import WorkflowEventBase
from grafi.common.events.component_base import create_component_events
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.message import Message
from grafi.common.models.message import Messages


# ============================================================================
# SERIALIZATION HELPERS
# ============================================================================


def serialize_topic_event(event: PublishToTopicEvent) -> Dict[str, Any]:
    """Serialize a PublishToTopicEvent."""
    return event.to_dict()


def deserialize_topic_event(data: Dict[str, Any]) -> PublishToTopicEvent:
    """Deserialize a PublishToTopicEvent."""
    return PublishToTopicEvent.from_dict(data)


def serialize_consume_events(
    events: List[ConsumeFromTopicEvent],
) -> List[Dict[str, Any]]:
    """Serialize a list of ConsumeFromTopicEvent."""
    return [event.to_dict() for event in events]


def deserialize_consume_events(
    data: List[Dict[str, Any]],
) -> List[ConsumeFromTopicEvent]:
    """Deserialize a list of ConsumeFromTopicEvent."""
    return [ConsumeFromTopicEvent.from_dict(event) for event in data]


def serialize_messages(messages: Messages) -> List[Dict[str, Any]]:
    """Serialize Messages to JSON object."""
    return [message.model_dump() for message in messages]


def deserialize_messages(data: List[Dict[str, Any]]) -> Messages:
    """Deserialize Messages from JSON object."""
    return [Message.model_validate(message) for message in data]


# ============================================================================
# NODE EVENTS
# ============================================================================

NodeInvokeEvent, NodeRespondEvent, NodeFailedEvent = create_component_events(
    base_class=NodeEventBase,
    component_name="NODE",
    input_type=List[ConsumeFromTopicEvent],
    output_type=PublishToTopicEvent,
    serialize_input_fn=serialize_consume_events,
    serialize_output_fn=serialize_topic_event,
    deserialize_input_fn=deserialize_consume_events,
    deserialize_output_fn=deserialize_topic_event,
)


# ============================================================================
# TOOL EVENTS
# ============================================================================

ToolInvokeEvent, ToolRespondEvent, ToolFailedEvent = create_component_events(
    base_class=ToolEventBase,
    component_name="TOOL",
    input_type=Messages,
    output_type=Messages,
    serialize_input_fn=serialize_messages,
    serialize_output_fn=serialize_messages,
    deserialize_input_fn=deserialize_messages,
    deserialize_output_fn=deserialize_messages,
)


# ============================================================================
# WORKFLOW EVENTS
# ============================================================================

(
    WorkflowInvokeEvent,
    WorkflowRespondEvent,
    WorkflowFailedEvent,
) = create_component_events(
    base_class=WorkflowEventBase,
    component_name="WORKFLOW",
    input_type=PublishToTopicEvent,
    output_type=List[ConsumeFromTopicEvent],
    serialize_input_fn=serialize_topic_event,
    serialize_output_fn=serialize_consume_events,
    deserialize_input_fn=deserialize_topic_event,
    deserialize_output_fn=deserialize_consume_events,
)


# ============================================================================
# ASSISTANT EVENTS
# ============================================================================

(
    AssistantInvokeEvent,
    AssistantRespondEvent,
    AssistantFailedEvent,
) = create_component_events(
    base_class=AssistantEventBase,
    component_name="ASSISTANT",
    input_type=PublishToTopicEvent,
    output_type=List[ConsumeFromTopicEvent],
    serialize_input_fn=serialize_topic_event,
    serialize_output_fn=serialize_consume_events,
    deserialize_input_fn=deserialize_topic_event,
    deserialize_output_fn=deserialize_consume_events,
)


# ============================================================================
# EXPORT ALL EVENT CLASSES
# ============================================================================

__all__ = [
    # Node events
    "NodeInvokeEvent",
    "NodeRespondEvent",
    "NodeFailedEvent",
    # Tool events
    "ToolInvokeEvent",
    "ToolRespondEvent",
    "ToolFailedEvent",
    # Workflow events
    "WorkflowInvokeEvent",
    "WorkflowRespondEvent",
    "WorkflowFailedEvent",
    # Assistant events
    "AssistantInvokeEvent",
    "AssistantRespondEvent",
    "AssistantFailedEvent",
]
