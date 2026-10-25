"""The record decorators of assistants, workflows, nodes and tools."""

from typing import Any

from grafi.common.decorators.record_base import ComponentConfig
from grafi.common.decorators.record_base import EventContext
from grafi.common.decorators.record_base import create_async_decorator
from grafi.common.events.component_events import AssistantFailedEvent
from grafi.common.events.component_events import AssistantInvokeEvent
from grafi.common.events.component_events import AssistantRespondEvent
from grafi.common.events.component_events import NodeFailedEvent
from grafi.common.events.component_events import NodeInvokeEvent
from grafi.common.events.component_events import NodeRespondEvent
from grafi.common.events.component_events import ToolFailedEvent
from grafi.common.events.component_events import ToolInvokeEvent
from grafi.common.events.component_events import ToolRespondEvent
from grafi.common.events.component_events import WorkflowFailedEvent
from grafi.common.events.component_events import WorkflowInvokeEvent
from grafi.common.events.component_events import WorkflowRespondEvent
from grafi.common.models.message import tool_messages


def _context(component: Any, component_id: str, **extra: Any) -> EventContext:
    return EventContext(
        id=component_id,
        name=component.name or "",
        type=component.type or "",
        oi_span_type=component.oi_span_type.value,
        **extra,
    )


record_assistant_invoke = create_async_decorator(
    ComponentConfig(
        invoke_event=AssistantInvokeEvent,
        respond_event=AssistantRespondEvent,
        failed_event=AssistantFailedEvent,
        extract_metadata=lambda self: _context(self, self.assistant_id),
        span_name_suffix="run",
        isolate_event_writes=True,
    )
)

record_workflow_invoke = create_async_decorator(
    ComponentConfig(
        invoke_event=WorkflowInvokeEvent,
        respond_event=WorkflowRespondEvent,
        failed_event=WorkflowFailedEvent,
        extract_metadata=lambda self: _context(self, self.workflow_id),
        isolate_event_writes=True,
    )
)

record_node_invoke = create_async_decorator(
    ComponentConfig(
        invoke_event=NodeInvokeEvent,
        respond_event=NodeRespondEvent,
        failed_event=NodeFailedEvent,
        extract_metadata=lambda self: _context(
            self,
            self.node_id,
            subscribed_topics=[
                topic.name for topic in self._subscribed_topics.values()
            ],
            publish_to_topics=[topic.name for topic in self.publish_to],
        ),
        # A node's publication, or None when it published nothing.
        output_of=lambda events: events[-1] if events else None,
    )
)

record_tool_invoke = create_async_decorator(
    ComponentConfig(
        invoke_event=ToolInvokeEvent,
        respond_event=ToolRespondEvent,
        failed_event=ToolFailedEvent,
        extract_metadata=lambda self: _context(self, self.tool_id),
        output_of=tool_messages,
    )
)
