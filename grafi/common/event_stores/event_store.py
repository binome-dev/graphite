"""Module for storing and managing events with optional file logging."""

from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Type

from loguru import logger

from grafi.common.events.component_events import AssistantFailedEvent
from grafi.common.events.component_events import AssistantInvokeEvent
from grafi.common.events.component_events import AssistantRespondEvent
from grafi.common.events.component_events import ConsumeFromTopicEvent
from grafi.common.events.component_events import NodeFailedEvent
from grafi.common.events.component_events import NodeInvokeEvent
from grafi.common.events.component_events import NodeRespondEvent
from grafi.common.events.component_events import ToolFailedEvent
from grafi.common.events.component_events import ToolInvokeEvent
from grafi.common.events.component_events import ToolRespondEvent
from grafi.common.events.component_events import WorkflowFailedEvent
from grafi.common.events.component_events import WorkflowInvokeEvent
from grafi.common.events.component_events import WorkflowRespondEvent
from grafi.common.events.event import Event
from grafi.common.events.event import EventType
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent


class EventStore(ABC):
    """Stores and manages events."""

    @abstractmethod
    async def record_event(self, event: Event) -> None: ...

    @abstractmethod
    async def record_events(self, events: List[Event]) -> None: ...

    @abstractmethod
    async def clear_events(self) -> None: ...

    @abstractmethod
    async def get_events(self) -> List[Event]: ...

    @abstractmethod
    async def get_event(self, event_id: str) -> Optional[Event]: ...

    @abstractmethod
    async def get_agent_events(self, assistant_request_id: str) -> List[Event]: ...

    @abstractmethod
    async def get_conversation_events(self, conversation_id: str) -> List[Event]: ...

    @abstractmethod
    async def get_topic_events(self, name: str, offsets: List[int]) -> List[Event]: ...

    def _create_event_from_dict(self, event_dict: Dict[str, Any]) -> Optional[Event]:
        """Create an event object from a dictionary."""
        event_type: Any = event_dict.get("event_type")
        if not isinstance(event_type, str):
            raise ValueError("Event type not found in event dict.")

        event_class = self._get_event_class(event_type)
        if event_class is None:
            raise ValueError(f"Event class not found for event type: {event_type}")

        try:
            return event_class.from_dict(data=event_dict)
        except Exception as e:
            logger.error(f"Failed to create event from dict: {e}")
            raise ValueError(f"Failed to create event from dict: {e}")

    def _get_event_class(self, event_type: str) -> Optional[Type[Event]]:
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
            EventType.WORKFLOW_RESPOND.value: WorkflowRespondEvent,
            EventType.ASSISTANT_FAILED.value: AssistantFailedEvent,
            EventType.ASSISTANT_INVOKE.value: AssistantInvokeEvent,
            EventType.ASSISTANT_RESPOND.value: AssistantRespondEvent,
            EventType.TOPIC_EVENT.value: TopicEvent,
            EventType.CONSUME_FROM_TOPIC.value: ConsumeFromTopicEvent,
            EventType.PUBLISH_TO_TOPIC.value: PublishToTopicEvent,
        }
        return event_classes.get(event_type)
