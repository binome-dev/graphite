"""Module for storing and managing events."""

from typing import List
from typing import Optional

from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.event import Event
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent


class EventStoreInMemory(EventStore):
    """Stores and manages events in memory by default."""

    events: List[Event] = []

    def __init__(self) -> None:
        """Initialize the event store."""
        self.events = []

    def record_event(self, event: Event) -> None:
        """Record an event to the store."""
        self.events.append(event)

    def record_events(self, events: List[Event]) -> None:
        """Record events to the store."""
        self.events.extend(events)

    def clear_events(self) -> None:
        """Clear all events."""
        self.events.clear()

    def get_events(self) -> List[Event]:
        """Get all events."""
        return self.events.copy()

    def get_event(self, event_id: str) -> Optional[Event]:
        """Get an event by ID."""
        for event in self.events:
            if event.event_id == event_id:
                return event
        return None

    def get_agent_events(self, assistant_request_id: str) -> List[Event]:
        """Get all events for a given agent request ID."""
        return [
            event
            for event in self.events
            if event.invoke_context.assistant_request_id == assistant_request_id
        ]

    def get_conversation_events(self, conversation_id: str) -> List[Event]:
        """Get all events for a given conversation ID."""
        return [
            event
            for event in self.events
            if event.invoke_context.conversation_id == conversation_id
        ]

    def get_topic_events(self, topic_name: str, offsets: List[int]) -> List[Event]:
        """Get all events for a given topic name and specific offsets."""

        # Convert offsets to a set for faster lookup
        offset_set = set(offsets)

        return [
            event
            for event in self.events
            if (
                isinstance(event, (PublishToTopicEvent, OutputTopicEvent))
                and hasattr(event, "topic_name")
                and event.topic_name == topic_name
                and event.offset in offset_set
            )
        ]
