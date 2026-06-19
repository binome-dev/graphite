"""Registry-based decoding of stored event dicts into :class:`Event` objects.

The codec owns event-type registration and decoding so that persistence
backends (``EventStore`` implementations) do not need to know concrete event
classes, and new event types can be registered without editing the store
(Open/Closed). Built-ins are registered here, at the composition boundary,
rather than imported into the persistence layer.
"""

from typing import Any
from typing import Dict
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


class EventCodec:
    """Maps event-type strings to event classes and decodes stored dicts."""

    def __init__(self, registry: Optional[Dict[str, Type[Event]]] = None) -> None:
        self._registry: Dict[str, Type[Event]] = dict(registry) if registry else {}

    def register(self, event_type: str, event_class: Type[Event]) -> None:
        """Register (or override) the class used to decode ``event_type``."""
        self._registry[event_type] = event_class

    def event_class(self, event_type: str) -> Optional[Type[Event]]:
        """Return the registered class for ``event_type``, or ``None``."""
        return self._registry.get(event_type)

    def decode(self, event_dict: Dict[str, Any]) -> Optional[Event]:
        """Decode one stored event dict into an :class:`Event`.

        Returns ``None`` (with a logged warning) instead of raising when an event
        is malformed or of an unknown type. Retrieval methods skip ``None``
        results, so one corrupt row cannot abort an entire ``get_agent_events`` /
        ``get_events`` call -- which would otherwise make a whole conversation
        (and any recovery that depends on it) unreadable.
        """
        event_id = event_dict.get("event_id", "<unknown>")
        event_type: Any = event_dict.get("event_type")
        if not isinstance(event_type, str):
            logger.warning(
                "Skipping event {} with missing/invalid event_type", event_id
            )
            return None

        event_class = self.event_class(event_type)
        if event_class is None:
            logger.warning(
                "Skipping event {} with unknown event type: {}", event_id, event_type
            )
            return None

        try:
            return event_class.from_dict(data=event_dict)
        except Exception as e:
            logger.error(
                "Skipping event {} that failed to deserialize: {}", event_id, e
            )
            return None


# The default codec, pre-registered with the framework's built-in event types.
# Downstream code can register additional types without editing any EventStore.
default_event_codec = EventCodec(
    {
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
)
