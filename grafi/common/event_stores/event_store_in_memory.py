"""Module for storing and managing events."""

from typing import List
from typing import Optional
from typing import Sequence
from typing import Set

from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.event import Event
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent


class EventStoreInMemory(EventStore):
    """Stores and manages events in memory by default.

    Recording is idempotent on ``event_id``: re-recording an event that has
    already been stored (e.g. on a retry or workflow replay) is a no-op, matching
    the Postgres store's ``ON CONFLICT DO NOTHING`` semantics. Events are returned
    in insertion order, which is the stable, causal order recovery relies on.
    """

    # Instance state is created in __init__; no mutable class-level default.
    events: List[Event]
    _event_ids: Set[str]

    def __init__(self) -> None:
        """Initialize the event store."""
        self.events = []
        self._event_ids = set()

    async def record_event(self, event: Event) -> None:
        """Record an event to the store (idempotent on event_id)."""
        await self.record_events([event])

    async def record_events(self, events: Sequence[Event]) -> None:
        """Record events to the store (idempotent on event_id)."""
        for event in events:
            if event.event_id in self._event_ids:
                continue
            self._event_ids.add(event.event_id)
            self.events.append(event)

    async def clear_events(self) -> None:
        """Clear all events."""
        self.events.clear()
        self._event_ids.clear()

    async def get_events(self) -> List[Event]:
        """Get all events."""
        return self.events.copy()

    async def get_event(self, event_id: str) -> Optional[Event]:
        """Get an event by ID."""
        for event in self.events:
            if event.event_id == event_id:
                return event
        return None

    async def get_agent_events(self, assistant_request_id: str) -> List[Event]:
        """Get all events for a given agent request ID."""
        return [
            event
            for event in self.events
            if event.invoke_context.assistant_request_id == assistant_request_id
        ]

    async def get_conversation_events(self, conversation_id: str) -> List[Event]:
        """Get all events for a given conversation ID."""
        return [
            event
            for event in self.events
            if event.invoke_context.conversation_id == conversation_id
        ]

    async def get_topic_events(self, name: str, offsets: List[int]) -> List[Event]:
        """Get all events for a given topic name and specific offsets."""

        # Convert offsets to a set for faster lookup
        offset_set = set(offsets)

        return [
            event
            for event in self.events
            if (
                isinstance(event, PublishToTopicEvent)
                and hasattr(event, "name")
                and event.name == name
                and event.offset in offset_set
            )
        ]
