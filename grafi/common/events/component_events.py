"""
Simplified event implementations using the base event framework.
This module replaces 20+ separate event files with a single, maintainable module.
"""

from typing import List
from typing import Optional

from grafi.common.events.component_base import AssistantEventBase
from grafi.common.events.component_base import NodeEventBase
from grafi.common.events.component_base import ToolEventBase
from grafi.common.events.component_base import WorkflowEventBase
from grafi.common.events.component_base import create_component_events
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.message import Messages

# ============================================================================
# NODE EVENTS
# ============================================================================

NodeInvokeEvent, NodeRespondEvent, NodeFailedEvent = create_component_events(
    base_class=NodeEventBase,
    component_name="NODE",
    input_type=List[ConsumeFromTopicEvent],
    output_type=Optional[PublishToTopicEvent],
    module=__name__,
)


# ============================================================================
# TOOL EVENTS
# ============================================================================

ToolInvokeEvent, ToolRespondEvent, ToolFailedEvent = create_component_events(
    base_class=ToolEventBase,
    component_name="TOOL",
    input_type=Messages,
    output_type=Messages,
    module=__name__,
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
    module=__name__,
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
    module=__name__,
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
