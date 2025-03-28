"""Module for storing and managing events with optional file logging."""

from typing import Any, Dict, List, Optional

from loguru import logger

from grafi.common.events.assistant_events.assistant_failed_event import (
    AssistantFailedEvent,
)
from grafi.common.events.assistant_events.assistant_invoke_event import (
    AssistantInvokeEvent,
)
from grafi.common.events.assistant_events.assistant_respond_event import (
    AssistantRespondEvent,
)
from grafi.common.events.event import Event, EventType
from grafi.common.events.node_events.node_failed_event import NodeFailedEvent
from grafi.common.events.node_events.node_invoke_event import NodeInvokeEvent
from grafi.common.events.node_events.node_respond_event import NodeRespondEvent
from grafi.common.events.tool_events.tool_failed_event import ToolFailedEvent
from grafi.common.events.tool_events.tool_invoke_event import ToolInvokeEvent
from grafi.common.events.tool_events.tool_respond_event import ToolRespondEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.events.workflow_events.workflow_failed_event import (
    WorkflowFailedEvent,
)
from grafi.common.events.workflow_events.workflow_invoke_event import (
    WorkflowInvokeEvent,
)


class EventStore:
    """Stores and manages events."""

    def record_event(self, event: Event) -> None:
        # record event to the store
        raise NotImplementedError

    def record_events(self, events: List[Event]) -> None:
        # record events to the store
        raise NotImplementedError

    def clear_events(self) -> None:
        """Clear all events."""
        raise NotImplementedError

    def get_events(self) -> List[Event]:
        """Get all events."""
        raise NotImplementedError

    def get_event(self, event_id: str) -> Optional[Event]:
        """Get an event by ID."""
        raise NotImplementedError

    def get_latest_node_event(self, node_id: str) -> Optional[Event]:
        """Get an event by node ID."""
        raise NotImplementedError

    def get_agent_events(self, assistant_request_id: str) -> List[Event]:
        """Get all events for a given agent request ID."""
        raise NotImplementedError

    def get_conversation_events(self, conversation_id: str) -> List[Event]:
        """Get all events for a given conversation ID."""
        raise NotImplementedError

    def get_unfinished_requests(
        self, assistant_type: str, assistant_name: str
    ) -> List[str]:
        """Get all assistant_request_id for unfinished requests."""
        raise NotImplementedError

    def _create_event_from_dict(self, event_dict: Dict[str, Any]) -> Optional[Event]:
        """Create an event object from a dictionary."""
        event_type = event_dict.get("event_type")
        if not event_type:
            raise ValueError("Event type not found in event dict.")

        event_class = self._get_event_class(event_type)
        if not event_class:
            raise ValueError(f"Event class not found for event type: {event_type}")

        try:
            event = event_class.from_dict(event_dict)
            return event
        except Exception as e:
            logger.error(f"Failed to create event from dict: {e}")
            raise ValueError(f"Failed to create event from dict: {e}")

    def _get_event_class(self, event_type: str) -> Optional[type]:
        """Get the event class based on the event type string."""
        event_classes = {
            EventType.NODE_FAILED.value: NodeFailedEvent,
            EventType.NODE_INVOKE.value: NodeInvokeEvent,
            EventType.NODE_RESPOND.value: NodeRespondEvent,
            EventType.TOOL_FAILED.value: ToolFailedEvent,
            EventType.TOOL_INVOKE.value: ToolInvokeEvent,
            EventType.TOOL_RESPOND.value: ToolRespondEvent,
            EventType.WORKFLOW_FAILED.value: WorkflowFailedEvent,
            EventType.WORKFLOW_INVOKE.value: WorkflowInvokeEvent,
            EventType.ASSISTANT_FAILED.value: AssistantFailedEvent,
            EventType.ASSISTANT_INVOKE.value: AssistantInvokeEvent,
            EventType.ASSISTANT_RESPOND.value: AssistantRespondEvent,
            EventType.TOPIC_EVENT.value: TopicEvent,
            EventType.CONSUME_FROM_TOPIC.value: ConsumeFromTopicEvent,
            EventType.PUBLISH_TO_TOPIC.value: PublishToTopicEvent,
        }
        return event_classes.get(event_type)
