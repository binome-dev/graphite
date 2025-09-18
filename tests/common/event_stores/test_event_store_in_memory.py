"""Tests for the in-memory event store implementation."""

from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict

import pytest

from grafi.common.event_stores.event_store import EventStore
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.events.event import Event
from grafi.common.events.event import EventType
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_types import TopicType


class SampleEvent(Event):
    """Test event implementation."""

    event_type: EventType = EventType.NODE_INVOKE
    test_data: str = "test"

    def to_dict(self) -> Dict[str, Any]:
        return {**self.event_dict(), "data": {"test_data": self.test_data}}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SampleEvent":
        base = cls.event_base(data)
        return cls(
            **base,
            test_data=data.get("data", {}).get("test_data", "test"),
            invoke_context=InvokeContext.model_validate(data.get("invoke_context", {})),
        )


@pytest.fixture
def event_store():
    """Create a fresh event store for each test."""
    return EventStoreInMemory()


@pytest.fixture
def sample_event():
    """Create a sample event for testing."""
    return SampleEvent(
        event_id="test-event-1",
        timestamp=datetime.now(timezone.utc).isoformat(),
        invoke_context=InvokeContext(
            conversation_id="conv-1",
            invoke_id="invoke-1",
            assistant_request_id="assist-1",
        ),
        test_data="sample data",
    )


@pytest.fixture
def multiple_events():
    """Create multiple events for testing."""
    events = []
    for i in range(5):
        events.append(
            SampleEvent(
                event_id=f"test-event-{i}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                invoke_context=InvokeContext(
                    conversation_id=f"conv-{i % 2}",  # Use 2 different conversations
                    invoke_id=f"invoke-{i}",
                    assistant_request_id=f"assist-{i % 3}",  # Use 3 different assistant requests
                ),
                test_data=f"data-{i}",
            )
        )
    return events


@pytest.fixture
def topic_events():
    """Create topic events for testing."""
    events = []
    for i in range(3):
        topic_event = PublishToTopicEvent(
            event_id=f"topic-event-{i}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            invoke_context=InvokeContext(
                conversation_id=f"conv-{i}",
                invoke_id=f"invoke-{i}",
                assistant_request_id=f"assist-{i}",
            ),
            name=f"topic-{i % 2}",  # Use 2 different topic names
            type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
            publisher_name="test_publisher",
            publisher_type="test",
            offset=i,
            data=[Message(role="user", content=f"Message {i}")],
        )
        events.append(topic_event)
    return events


class TestEventStoreInMemory:
    """Test suite for in-memory event store."""

    @pytest.mark.asyncio
    async def test_initialization(self, event_store: EventStore):
        """Test that the event store initializes correctly."""
        assert event_store is not None
        assert await event_store.a_get_events() == []

    @pytest.mark.asyncio
    async def test_record_single_event(self, event_store: EventStore, sample_event):
        """Test recording a single event to the store."""
        await event_store.a_record_event(sample_event)

        events = await event_store.a_get_events()
        assert len(events) == 1
        assert events[0].event_id == sample_event.event_id

    @pytest.mark.asyncio
    async def test_record_multiple_events_separately(
        self, event_store: EventStore, multiple_events
    ):
        """Test recording multiple events separately."""
        for event in multiple_events:
            await event_store.a_record_event(event)

        events = await event_store.a_get_events()
        assert len(events) == len(multiple_events)

        # Check events are in order
        for i, event in enumerate(events):
            assert event.event_id == f"test-event-{i}"

    @pytest.mark.asyncio
    async def test_record_events_batch(self, event_store: EventStore, multiple_events):
        """Test recording multiple events in batch."""
        await event_store.a_record_events(multiple_events)

        events = await event_store.a_get_events()
        assert len(events) == len(multiple_events)

        # Check events are in order
        for i, event in enumerate(events):
            assert event.event_id == f"test-event-{i}"

    @pytest.mark.asyncio
    async def test_get_event_by_id(self, event_store: EventStore, sample_event):
        """Test getting an event by ID."""
        await event_store.a_record_event(sample_event)

        retrieved_event = await event_store.a_get_event(sample_event.event_id)
        assert retrieved_event is not None
        assert retrieved_event.event_id == sample_event.event_id
        assert retrieved_event is sample_event

    @pytest.mark.asyncio
    async def test_get_event_by_nonexistent_id(self, event_store: EventStore):
        """Test getting an event by non-existent ID."""
        result = await event_store.a_get_event("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_conversation_events(
        self, event_store: EventStore, multiple_events
    ):
        """Test filtering events by conversation ID."""
        for event in multiple_events:
            await event_store.a_record_event(event)

        # Get events for conv-0
        conv_0_events = await event_store.a_get_conversation_events("conv-0")
        assert len(conv_0_events) == 3  # Events 0, 2, 4
        for event in conv_0_events:
            assert event.invoke_context.conversation_id == "conv-0"

        # Get events for conv-1
        conv_1_events = await event_store.a_get_conversation_events("conv-1")
        assert len(conv_1_events) == 2  # Events 1, 3
        for event in conv_1_events:
            assert event.invoke_context.conversation_id == "conv-1"

        # Get events for non-existent conversation
        no_events = await event_store.a_get_conversation_events("conv-999")
        assert no_events == []

    @pytest.mark.asyncio
    async def test_get_agent_events(self, event_store: EventStore, multiple_events):
        """Test filtering events by assistant request ID."""
        for event in multiple_events:
            await event_store.a_record_event(event)

        # Get events for assist-0
        assist_0_events = await event_store.a_get_agent_events("assist-0")
        assert len(assist_0_events) == 2  # Events 0, 3
        for event in assist_0_events:
            assert event.invoke_context.assistant_request_id == "assist-0"

        # Get events for assist-1
        assist_1_events = await event_store.a_get_agent_events("assist-1")
        assert len(assist_1_events) == 2  # Events 1, 4
        for event in assist_1_events:
            assert event.invoke_context.assistant_request_id == "assist-1"

        # Get events for assist-2
        assist_2_events = await event_store.a_get_agent_events("assist-2")
        assert len(assist_2_events) == 1  # Event 2
        for event in assist_2_events:
            assert event.invoke_context.assistant_request_id == "assist-2"

    @pytest.mark.asyncio
    async def test_get_topic_events(self, event_store: EventStore, topic_events):
        """Test filtering events by topic name and offsets."""
        for event in topic_events:
            await event_store.a_record_event(event)

        # Get events for topic-0 with specific offsets
        topic_0_events = await event_store.a_get_topic_events("topic-0", [0, 2])
        assert len(topic_0_events) == 2  # Events 0, 2
        for event in topic_0_events:
            assert event.name == "topic-0"
            assert event.offset in [0, 2]

        # Get events for topic-1 with specific offset
        topic_1_events = await event_store.a_get_topic_events("topic-1", [1])
        assert len(topic_1_events) == 1  # Event 1
        assert topic_1_events[0].name == "topic-1"
        assert topic_1_events[0].offset == 1

        # Get events for non-existent topic
        no_events = await event_store.a_get_topic_events("non-existent", [0])
        assert no_events == []

    @pytest.mark.asyncio
    async def test_clear_events(self, event_store: EventStore, multiple_events):
        """Test clearing all events from the store."""
        for event in multiple_events:
            event_store.record_event(event)

        assert len(await event_store.a_get_events()) == 5
        await event_store.a_clear_events()
        assert len(await event_store.a_get_events()) == 0

    @pytest.mark.asyncio
    async def test_event_persistence_in_memory(
        self, event_store: EventStore, sample_event
    ):
        """Test that events persist in memory between operations."""
        await event_store.a_record_event(sample_event)

        # Add another event
        another_event = SampleEvent(
            event_id="test-event-2",
            timestamp=datetime.now(timezone.utc).isoformat(),
            invoke_context=InvokeContext(
                conversation_id="conv-2",
                invoke_id="invoke-2",
                assistant_request_id="assist-2",
            ),
            test_data="another data",
        )
        await event_store.a_record_event(another_event)

        # Original event should still be there
        all_events = await event_store.a_get_events()
        assert len(all_events) == 2
        assert all_events[0].event_id == sample_event.event_id
        assert all_events[1].event_id == another_event.event_id

    @pytest.mark.asyncio
    async def test_empty_filters(self, event_store: EventStore):
        """Test filtering on empty event store."""
        assert await event_store.a_get_conversation_events("any") == []
        assert await event_store.a_get_agent_events("any") == []
        assert await event_store.a_get_topic_events("any", [0]) == []
        assert await event_store.a_get_event("any") is None

    @pytest.mark.asyncio
    async def test_event_ordering_preserved(self, event_store: EventStore):
        """Test that event insertion order is preserved."""
        events = []
        for i in range(10):
            event = SampleEvent(
                event_id=f"ordered-{i}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                invoke_context=InvokeContext(
                    conversation_id="conv",
                    invoke_id="invoke",
                    assistant_request_id="assist",
                ),
                test_data=f"ordered-data-{i}",
            )
            events.append(event)
            await event_store.a_record_event(event)

        stored_events = await event_store.a_get_events()
        for i, event in enumerate(stored_events):
            assert event.event_id == f"ordered-{i}"
            assert event.test_data == f"ordered-data-{i}"

    @pytest.mark.asyncio
    async def test_get_events_returns_copy(self, event_store: EventStore, sample_event):
        """Test that get_events returns a copy, not the original list."""
        await event_store.a_record_event(sample_event)

        events1 = await event_store.a_get_events()
        events2 = await event_store.a_get_events()

        # Should be different list instances
        assert events1 is not events2
        # But contain the same events
        assert len(events1) == len(events2) == 1
        assert events1[0] is events2[0]  # Same event object

    @pytest.mark.asyncio
    async def test_mixed_event_types(
        self, event_store: EventStore, sample_event, topic_events
    ):
        """Test handling mixed event types."""
        # Record both regular events and topic events
        await event_store.a_record_event(sample_event)
        await event_store.a_record_events(topic_events)

        all_events = await event_store.a_get_events()
        assert len(all_events) == 4  # 1 sample + 3 topic events

        # Should be able to retrieve by conversation
        conv_0_events = await event_store.a_get_conversation_events("conv-0")
        assert len(conv_0_events) == 1  # Only topic-event-0

        # Should be able to retrieve topic events
        topic_0_events = await event_store.a_get_topic_events("topic-0", [0, 2])
        assert len(topic_0_events) == 2
