"""The record decorators of assistants, workflows, nodes and tools."""

from typing import Any
from typing import Iterable
from typing import List
from typing import Optional
from typing import TypeVar

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
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.message import Message
from grafi.common.models.message import Messages

E = TypeVar("E", bound=TopicEvent)


def _context(component: Any, component_id: str, **extra: Any) -> EventContext:
    return EventContext(
        id=component_id,
        name=component.name or "",
        type=component.type or "",
        oi_span_type=component.oi_span_type.value,
        **extra,
    )


def _joined_stream(batches: Iterable[Messages]) -> Optional[Message]:
    """The streamed chunks among ``batches`` joined into one message, or None
    when nothing was streamed."""
    streamed = [m for messages in batches for m in messages if m.is_streaming]
    if not streamed:
        return None
    text = "".join(m.content for m in streamed if isinstance(m.content, str))
    return Message(role="assistant", content=text)


def _outputs(events: List[E]) -> List[E]:
    """The events a component yielded, a stream joined into the last of them."""
    joined = _joined_stream(event.data for event in events)
    if joined is None:
        return events
    return [events[-1].model_copy(update={"data": [joined]}, deep=True)]


def _messages(batches: List[Messages]) -> Messages:
    """A tool's messages, a stream joined into one."""
    joined = _joined_stream(batches)
    if joined is None:
        return [message for messages in batches for message in messages]
    return [joined]


record_assistant_invoke = create_async_decorator(
    ComponentConfig(
        invoke_event=AssistantInvokeEvent,
        respond_event=AssistantRespondEvent,
        failed_event=AssistantFailedEvent,
        extract_metadata=lambda self: _context(
            self, self.assistant_id, model=getattr(self, "model", "")
        ),
        process_async_result=_outputs,
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
        process_async_result=_outputs,
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
        # A node's last publication, or None when it published nothing.
        process_async_result=lambda events: _outputs(events)[-1] if events else None,
    )
)

record_tool_invoke = create_async_decorator(
    ComponentConfig(
        invoke_event=ToolInvokeEvent,
        respond_event=ToolRespondEvent,
        failed_event=ToolFailedEvent,
        extract_metadata=lambda self: _context(self, self.tool_id),
        process_async_result=_messages,
    )
)
