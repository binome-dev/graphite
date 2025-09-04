# mypy: ignore-errors
"""
Unified module for all record decorators.
This replaces 8 separate files with a single, maintainable module.
"""

from typing import List
from typing import Union

from grafi.common.decorators.record_base import ComponentConfig
from grafi.common.decorators.record_base import EventContext
from grafi.common.decorators.record_base import create_async_decorator
from grafi.common.decorators.record_base import create_sync_decorator

# Import event types
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
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.message import Message


# ============================================================================
# ASSISTANT DECORATORS
# ============================================================================


def process_async_result(
    args: List[Union[ConsumeFromTopicEvent]],
) -> List[Union[ConsumeFromTopicEvent]]:
    result_content = ""
    is_streaming = False
    for event in args:
        for message in event.data:
            if message.is_streaming:
                if message.content is not None and isinstance(message.content, str):
                    result_content += message.content
                is_streaming = True

    if is_streaming:
        streaming_consumed_event = args[-1].model_copy(
            update={"data": [Message(role="assistant", content=result_content)]},
            deep=True,
        )
        return [streaming_consumed_event]

    return args


_assistant_config = ComponentConfig(
    event_types={
        "invoke": AssistantInvokeEvent,
        "respond": AssistantRespondEvent,
        "failed": AssistantFailedEvent,
    },
    extract_metadata=lambda self: EventContext(
        id=self.assistant_id,
        name=self.name or "",
        type=self.type or "",
        oi_span_type=self.oi_span_type.value,
        model=getattr(self, "model", ""),
    ),
    process_async_result=process_async_result,
    span_name_suffix="run",
)

# Sync assistant decorator
record_assistant_invoke = create_sync_decorator(_assistant_config)

# Async assistant decorator
record_assistant_a_invoke = create_async_decorator(_assistant_config)

# ============================================================================
# WORKFLOW DECORATORS
# ============================================================================

_workflow_config = ComponentConfig(
    event_types={
        "invoke": WorkflowInvokeEvent,
        "respond": WorkflowRespondEvent,
        "failed": WorkflowFailedEvent,
    },
    extract_metadata=lambda self: EventContext(
        id=self.workflow_id,
        name=self.name or "",
        type=self.type or "",
        oi_span_type=self.oi_span_type.value,
    ),
    process_async_result=process_async_result,
    span_name_suffix="invoke",
)

# Sync workflow decorator
record_workflow_invoke = create_sync_decorator(_workflow_config)

# Async workflow decorator
record_workflow_a_invoke = create_async_decorator(_workflow_config)


# ============================================================================
# NODE DECORATORS
# ============================================================================


def process_node_async_result(
    args: List[Union[PublishToTopicEvent]],
) -> List[Union[PublishToTopicEvent]]:
    result_content = ""
    is_streaming = False
    for event in args:
        for message in event.data:
            if message.is_streaming:
                if message.content is not None and isinstance(message.content, str):
                    result_content += message.content
                is_streaming = True

    if is_streaming:
        streaming_consumed_event = args[-1].model_copy(
            update={"data": [Message(role="assistant", content=result_content)]},
            deep=True,
        )
        return streaming_consumed_event

    return args[-1]


_node_config = ComponentConfig(
    event_types={
        "invoke": NodeInvokeEvent,
        "respond": NodeRespondEvent,
        "failed": NodeFailedEvent,
    },
    extract_metadata=lambda self: EventContext(
        id=self.node_id,
        name=self.name or "",
        type=self.type or "",
        oi_span_type=self.oi_span_type.value,
        subscribed_topics=[topic.name for topic in self._subscribed_topics.values()],
        publish_to_topics=[topic.name for topic in self.publish_to],
    ),
    process_async_result=process_node_async_result,
    span_name_suffix="invoke",
)

# Sync node decorator
record_node_invoke = create_sync_decorator(_node_config)

# Async node decorator
record_node_a_invoke = create_async_decorator(_node_config)


# ============================================================================
# TOOL DECORATORS
# ============================================================================
def process_messages_streaming_result(
    args: List[List[Message]],
) -> List[Message]:
    result_content = ""
    is_streaming = False
    for messages in args:
        for message in messages:
            if message.is_streaming:
                if message.content is not None and isinstance(message.content, str):
                    result_content += message.content
                is_streaming = True

    if is_streaming:
        return [Message(role="assistant", content=result_content)]
    else:  # Non-streaming, return all messages
        return [msg for messages in args for msg in messages]


_tool_config = ComponentConfig(
    event_types={
        "invoke": ToolInvokeEvent,
        "respond": ToolRespondEvent,
        "failed": ToolFailedEvent,
    },
    extract_metadata=lambda self: EventContext(
        id=self.tool_id,
        name=self.name or "",
        type=self.type or "",
        oi_span_type=self.oi_span_type.value,
    ),
    process_async_result=process_messages_streaming_result,
    span_name_suffix="invoke",
)

# Sync tool decorator
record_tool_invoke = create_sync_decorator(_tool_config)

# Async tool decorator
record_tool_a_invoke = create_async_decorator(_tool_config)
