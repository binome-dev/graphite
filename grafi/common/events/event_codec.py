"""Encoding and decoding the events a store keeps.

The codec knows the event classes, by their ``event_type``, so that a store
need not: it encodes an event to store, and decodes a stored one. grafi's own
event types are registered here; another is registered with ``register()``.

An event is stored as its JSON form, ``model_dump(mode="json")``, whose
``event_version`` names its revision (see ``EVENT_VERSION``). Decoding upgrades
an event of an earlier revision first, as ``grafi.common.events.event_v1`` does,
and fails loudly on one it cannot read: an event store is the record a
workflow is recovered from, so an event is never skipped.
"""

from typing import Any
from typing import Callable
from typing import Dict
from typing import Mapping
from typing import Optional
from typing import Type

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
from grafi.common.events.event import EVENT_VERSION
from grafi.common.events.event import Event
from grafi.common.events.event import EventType
from grafi.common.events.event_v1 import upcast_v1
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions.event_exceptions import EventSerializationError

# Each earlier revision's upgrade to the next, by revision.
_UPCASTERS: Dict[int, Callable[[Mapping[str, Any]], Dict[str, Any]]] = {1: upcast_v1}


def _version(value: Any) -> Optional[int]:
    """An event's revision: an integer, or ``"1.0"`` for the first."""
    if value == "1.0":
        return 1
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class EventCodec:
    """Maps event-type strings to event classes, and encodes and decodes the
    events stored."""

    def __init__(self, registry: Optional[Dict[str, Type[Event]]] = None) -> None:
        self._registry: Dict[str, Type[Event]] = dict(registry) if registry else {}

    def register(self, event_type: str, event_class: Type[Event]) -> None:
        """Register (or override) the class used to decode ``event_type``."""
        self._registry[event_type] = event_class

    def event_class(self, event_type: str) -> Optional[Type[Event]]:
        """Return the registered class for ``event_type``, or ``None``."""
        return self._registry.get(event_type)

    def encode(self, event: Event) -> Dict[str, Any]:
        """``event`` as stored: its JSON form.

        Raises:
            EventSerializationError: If it holds a value JSON cannot hold, or is
                not of the class its type decodes as, so it could not be read
                back.
        """
        event_type = str(getattr(event.event_type, "value", event.event_type))
        if self.event_class(event_type) is not type(event):
            raise EventSerializationError(
                f"Event {event.event_id} is a {type(event).__name__}, which this "
                f"codec does not decode {event_type!r} as; register it with "
                "EventCodec.register(), so it can be read back."
            )
        try:
            return event.model_dump(mode="json")
        except Exception as error:
            raise EventSerializationError(
                f"Event {event.event_id} ({event_type}) cannot be encoded: {error}",
                cause=error,
            ) from error

    def decode(self, event_dict: Mapping[str, Any]) -> Event:
        """Decode one stored event, upgrading it from an earlier revision.

        Raises:
            EventSerializationError: For an event of a revision newer than this
                grafi's, or of no known revision or type, or that does not
                match its class; the cause, if any, is chained.
        """
        if not isinstance(event_dict, Mapping):
            raise EventSerializationError(
                f"A stored event is a JSON object, not {type(event_dict).__name__}."
            )
        event_id = event_dict.get("event_id", "<unknown>")
        version = _version(event_dict.get("event_version"))
        if version is None or version > EVENT_VERSION:
            raise EventSerializationError(
                f"Event {event_id} has version {event_dict.get('event_version')!r}; "
                f"this grafi reads versions up to {EVENT_VERSION}."
            )
        event_type = event_dict.get("event_type")
        event_class = (
            self.event_class(event_type) if isinstance(event_type, str) else None
        )
        if event_class is None:
            raise EventSerializationError(
                f"Event {event_id} has an unknown event type {event_type!r}; "
                "register its class with EventCodec.register()."
            )
        try:
            while version < EVENT_VERSION:
                event_dict = _UPCASTERS[version](event_dict)
                version += 1
            return event_class.model_validate(event_dict)
        except Exception as error:
            raise EventSerializationError(
                f"Event {event_id} ({event_type}) cannot be decoded: {error}",
                cause=error,
            ) from error


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
