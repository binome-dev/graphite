"""Module for storing and managing events."""

from typing import List, Optional

from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.event import Event, EventType
from grafi.common.events.node_events.node_respond_event import NodeRespondEvent


class EventStoreInMemory(EventStore):
    """Stores and manages events in memory by default."""

    events: List[Event] = []

    def __init__(self):
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

    def get_latest_node_event(self, node_id: str) -> Optional[Event]:
        """Get the latest event for a given node ID."""
        for event in reversed(self.events):
            if isinstance(event, NodeRespondEvent) and event.node_id == node_id:
                return event
        return None

    def get_agent_events(self, assistant_request_id: str) -> List[Event]:
        """Get all events for a given agent request ID."""
        return [
            event
            for event in self.events
            if event.execution_context.assistant_request_id == assistant_request_id
        ]

    def get_conversation_events(self, conversation_id: str) -> List[Event]:
        """Get all events for a given conversation ID."""
        return [
            event
            for event in self.events
            if event.execution_context.conversation_id == conversation_id
        ]

    def get_unfinished_requests(
        self, assistant_type: str, assistant_name: str
    ) -> List[str]:
        """Get all assistant_request_id for unfinished requests."""
        # Collect all assistant_request_ids for the given assistant_type and assistant_name
        assistant_request_ids = set(
            event.execution_context.assistant_request_id
            for event in self.events
            if getattr(event, "assistant_type", None) == assistant_type
            and getattr(event, "assistant_name", None) == assistant_name
        )

        # Identify finished requests (those with an AssistantRespondEvent)
        finished_request_ids = set(
            event.execution_context.assistant_request_id
            for event in self.events
            if event.event_type == EventType.ASSISTANT_RESPOND
            and getattr(event, "assistant_type", None) == assistant_type
            and getattr(event, "assistant_name", None) == assistant_name
        )

        # Unfinished requests are those started but not finished
        unfinished_request_ids = assistant_request_ids - finished_request_ids
        return list(unfinished_request_ids)
