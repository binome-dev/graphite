"""Tests for the in-memory event store implementation."""

from datetime import datetime
from datetime import timezone

import pytest

from grafi.common.event_stores.event_store import EventStore
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.events.event import Event
from grafi.common.events.event import EventType
from grafi.common.events.event_codec import EventCodec
from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import EventSerializationError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_types import TopicType
from tests.events.event_fixtures import every_event


class SampleEvent(Event):
    """An event of a type of its own, which only a store that keeps events as
    they are (not strict) can hold."""

    event_type: EventType = EventType.NODE_INVOKE
    test_data: str = "test"


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
        assert await event_store.get_events() == []

    @pytest.mark.asyncio
    async def test_record_single_event(self, event_store: EventStore, sample_event):
        """Test recording a single event to the store."""
        await event_store.record_event(sample_event)

        events = await event_store.get_events()
        assert len(events) == 1
        assert events[0].event_id == sample_event.event_id

    @pytest.mark.asyncio
    async def test_record_multiple_events_separately(
        self, event_store: EventStore, multiple_events
    ):
        """Test recording multiple events separately."""
        for event in multiple_events:
            await event_store.record_event(event)

        events = await event_store.get_events()
        assert len(events) == len(multiple_events)

        # Check events are in order
        for i, event in enumerate(events):
            assert event.event_id == f"test-event-{i}"

    @pytest.mark.asyncio
    async def test_record_events_batch(self, event_store: EventStore, multiple_events):
        """Test recording multiple events in batch."""
        await event_store.record_events(multiple_events)

        events = await event_store.get_events()
        assert len(events) == len(multiple_events)

        # Check events are in order
        for i, event in enumerate(events):
            assert event.event_id == f"test-event-{i}"

    @pytest.mark.asyncio
    async def test_record_event_is_idempotent(
        self, event_store: EventStore, sample_event
    ):
        """Re-recording the same event_id is a no-op (replay/retry safe)."""
        await event_store.record_event(sample_event)
        await event_store.record_event(sample_event)

        events = await event_store.get_events()
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_record_events_dedups_within_and_across_calls(
        self, event_store: EventStore, multiple_events
    ):
        """Duplicate event_ids are skipped, not appended, across batches."""
        await event_store.record_events(multiple_events)
        # Replay the same batch (e.g. recovery) plus a duplicate within the batch.
        await event_store.record_events(multiple_events + [multiple_events[0]])

        events = await event_store.get_events()
        assert len(events) == len(multiple_events)
        assert len({e.event_id for e in events}) == len(multiple_events)

    @pytest.mark.asyncio
    async def test_clear_resets_idempotency_index(
        self, event_store: EventStore, sample_event
    ):
        """After clearing, an event with a previously-seen id can be re-recorded."""
        await event_store.record_event(sample_event)
        await event_store.clear_events()
        await event_store.record_event(sample_event)

        events = await event_store.get_events()
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_get_event_by_id(self, event_store: EventStore, sample_event):
        """Test getting an event by ID."""
        await event_store.record_event(sample_event)

        retrieved_event = await event_store.get_event(sample_event.event_id)
        assert retrieved_event is not None
        assert retrieved_event.event_id == sample_event.event_id
        assert retrieved_event is sample_event

    @pytest.mark.asyncio
    async def test_get_event_by_nonexistent_id(self, event_store: EventStore):
        """Test getting an event by non-existent ID."""
        result = await event_store.get_event("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_conversation_events(
        self, event_store: EventStore, multiple_events
    ):
        """Test filtering events by conversation ID."""
        for event in multiple_events:
            await event_store.record_event(event)

        # Get events for conv-0
        conv_0_events = await event_store.get_conversation_events("conv-0")
        assert len(conv_0_events) == 3  # Events 0, 2, 4
        for event in conv_0_events:
            assert event.invoke_context.conversation_id == "conv-0"

        # Get events for conv-1
        conv_1_events = await event_store.get_conversation_events("conv-1")
        assert len(conv_1_events) == 2  # Events 1, 3
        for event in conv_1_events:
            assert event.invoke_context.conversation_id == "conv-1"

        # Get events for non-existent conversation
        no_events = await event_store.get_conversation_events("conv-999")
        assert no_events == []

    @pytest.mark.asyncio
    async def test_get_agent_events(self, event_store: EventStore, multiple_events):
        """Test filtering events by assistant request ID."""
        for event in multiple_events:
            await event_store.record_event(event)

        # Get events for assist-0
        assist_0_events = await event_store.get_agent_events("assist-0")
        assert len(assist_0_events) == 2  # Events 0, 3
        for event in assist_0_events:
            assert event.invoke_context.assistant_request_id == "assist-0"

        # Get events for assist-1
        assist_1_events = await event_store.get_agent_events("assist-1")
        assert len(assist_1_events) == 2  # Events 1, 4
        for event in assist_1_events:
            assert event.invoke_context.assistant_request_id == "assist-1"

        # Get events for assist-2
        assist_2_events = await event_store.get_agent_events("assist-2")
        assert len(assist_2_events) == 1  # Event 2
        for event in assist_2_events:
            assert event.invoke_context.assistant_request_id == "assist-2"

    @pytest.mark.asyncio
    async def test_get_topic_events(self, event_store: EventStore, topic_events):
        """Test filtering events by topic name and offsets."""
        for event in topic_events:
            await event_store.record_event(event)

        # Get events for topic-0 with specific offsets
        topic_0_events = await event_store.get_topic_events("topic-0", [0, 2])
        assert len(topic_0_events) == 2  # Events 0, 2
        for event in topic_0_events:
            assert event.name == "topic-0"
            assert event.offset in [0, 2]

        # Get events for topic-1 with specific offset
        topic_1_events = await event_store.get_topic_events("topic-1", [1])
        assert len(topic_1_events) == 1  # Event 1
        assert topic_1_events[0].name == "topic-1"
        assert topic_1_events[0].offset == 1

        # Get events for non-existent topic
        no_events = await event_store.get_topic_events("non-existent", [0])
        assert no_events == []

    @pytest.mark.asyncio
    async def test_clear_events(self, event_store: EventStore, multiple_events):
        """Test clearing all events from the store."""
        for event in multiple_events:
            await event_store.record_event(event)

        assert len(await event_store.get_events()) == 5
        await event_store.clear_events()
        assert len(await event_store.get_events()) == 0

    @pytest.mark.asyncio
    async def test_event_persistence_in_memory(
        self, event_store: EventStore, sample_event
    ):
        """Test that events persist in memory between operations."""
        await event_store.record_event(sample_event)

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
        await event_store.record_event(another_event)

        # Original event should still be there
        all_events = await event_store.get_events()
        assert len(all_events) == 2
        assert all_events[0].event_id == sample_event.event_id
        assert all_events[1].event_id == another_event.event_id

    @pytest.mark.asyncio
    async def test_empty_filters(self, event_store: EventStore):
        """Test filtering on empty event store."""
        assert await event_store.get_conversation_events("any") == []
        assert await event_store.get_agent_events("any") == []
        assert await event_store.get_topic_events("any", [0]) == []
        assert await event_store.get_event("any") is None

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
            await event_store.record_event(event)

        stored_events = await event_store.get_events()
        for i, event in enumerate(stored_events):
            assert event.event_id == f"ordered-{i}"
            assert event.test_data == f"ordered-data-{i}"

    @pytest.mark.asyncio
    async def test_get_events_returns_copy(self, event_store: EventStore, sample_event):
        """Test that get_events returns a copy, not the original list."""
        await event_store.record_event(sample_event)

        events1 = await event_store.get_events()
        events2 = await event_store.get_events()

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
        await event_store.record_event(sample_event)
        await event_store.record_events(topic_events)

        all_events = await event_store.get_events()
        assert len(all_events) == 4  # 1 sample + 3 topic events

        # Should be able to retrieve by conversation
        conv_0_events = await event_store.get_conversation_events("conv-0")
        assert len(conv_0_events) == 1  # Only topic-event-0

        # Should be able to retrieve topic events
        topic_0_events = await event_store.get_topic_events("topic-0", [0, 2])
        assert len(topic_0_events) == 2


class TestEventDecodingIsLoud:
    """A stored event that cannot be decoded raises: it is never skipped, as a
    store is the record a workflow is recovered from."""

    def test_missing_event_type_raises(self):
        store = EventStoreInMemory()
        with pytest.raises(EventSerializationError):
            store.codec.decode({"event_id": "x", "event_version": 2})

    def test_unknown_event_type_raises(self):
        store = EventStoreInMemory()
        with pytest.raises(EventSerializationError, match="NotARealType"):
            store.codec.decode(
                {"event_id": "x", "event_version": 2, "event_type": "NotARealType"}
            )

    def test_corrupt_payload_raises(self):
        store = EventStoreInMemory()
        # A valid type, but missing the fields its class requires.
        with pytest.raises(EventSerializationError, match="cannot be decoded"):
            store.codec.decode(
                {"event_id": "x", "event_version": 2, "event_type": "NodeInvoke"}
            )

    def test_newer_version_raises(self, topic_events):
        store = EventStoreInMemory()
        stored = {**store.codec.encode(topic_events[0]), "event_version": 3}
        with pytest.raises(EventSerializationError, match="version 3"):
            store.codec.decode(stored)


class TestEventStoreCodec:
    """A store encodes and decodes events with its codec: the default, shared by
    every store, or one of its own."""

    def test_a_store_uses_the_default_codec(self):
        assert EventStore.codec is default_event_codec
        assert EventStoreInMemory().codec is default_event_codec

    @pytest.mark.asyncio
    async def test_a_store_given_a_codec_of_its_own_uses_it(self, sample_event):
        store = EventStoreInMemory(strict=True)
        with pytest.raises(EventSerializationError, match="SampleEvent"):
            await store.record_event(sample_event)  # Decoded as NodeInvoke's.

        store.codec = EventCodec({EventType.NODE_INVOKE.value: SampleEvent})
        await store.record_event(sample_event)

        assert await store.get_events() == [sample_event]
        assert EventStoreInMemory().codec is default_event_codec  # Unchanged.
        assert default_event_codec.event_class("NodeInvoke") is not SampleEvent


class TestStrictEventStore:
    """A strict store keeps each event as a durable store does: encoded as JSON,
    and decoded back."""

    @pytest.mark.asyncio
    async def test_every_event_type_round_trips(self):
        store = EventStoreInMemory(strict=True)
        events = every_event()
        await store.record_events(events)

        stored = await store.get_events()
        assert stored == events
        assert [type(event) for event in stored] == [type(event) for event in events]
        # Rebuilt from their JSON form, not the very objects recorded.
        assert all(kept is not event for kept, event in zip(stored, events))

    @pytest.mark.asyncio
    async def test_record_event_round_trips(self, topic_events):
        store = EventStoreInMemory(strict=True)
        await store.record_event(topic_events[0])
        assert await store.get_event(topic_events[0].event_id) == topic_events[0]

    @pytest.mark.asyncio
    async def test_queries_find_the_decoded_events(self, topic_events):
        store = EventStoreInMemory(strict=True)
        await store.record_events(topic_events)
        assert await store.get_topic_events("topic-0", [0, 2]) == [
            topic_events[0],
            topic_events[2],
        ]
        assert await store.get_conversation_events("conv-1") == [topic_events[1]]
        assert await store.get_agent_events("assist-2") == [topic_events[2]]

    @pytest.mark.asyncio
    async def test_a_batch_with_an_unencodable_event_records_nothing(
        self, topic_events
    ):
        store = EventStoreInMemory(strict=True)
        unencodable = topic_events[1].model_copy(
            update={
                "invoke_context": topic_events[1].invoke_context.model_copy(
                    update={"kwargs": {"client": object()}}
                )
            }
        )
        # Encoding fails (as model_dump(mode="json") does), before any is kept.
        with pytest.raises(EventSerializationError, match="cannot be encoded"):
            await store.record_events([topic_events[0], unencodable, topic_events[2]])
        assert await store.get_events() == []

        # The store still takes the events that can be recorded.
        await store.record_events([topic_events[0], topic_events[2]])
        assert await store.get_events() == [topic_events[0], topic_events[2]]

    @pytest.mark.asyncio
    async def test_a_batch_with_an_undecodable_event_records_nothing(
        self, topic_events, sample_event
    ):
        # SampleEvent says it is a NodeInvoke, which it cannot be decoded as:
        # refused as it is encoded, before any is kept.
        store = EventStoreInMemory(strict=True)
        with pytest.raises(EventSerializationError, match="SampleEvent"):
            await store.record_events([topic_events[0], sample_event])
        assert await store.get_events() == []

    @pytest.mark.asyncio
    async def test_an_unencodable_event_is_not_recorded(self, topic_events):
        store = EventStoreInMemory(strict=True)
        unencodable = topic_events[0].model_copy(
            update={
                "invoke_context": topic_events[0].invoke_context.model_copy(
                    update={"kwargs": {"client": object()}}
                )
            }
        )
        with pytest.raises(EventSerializationError, match="cannot be encoded"):
            await store.record_event(unencodable)
        assert await store.get_events() == []
        # Its id was not taken: the event, made encodable, can be recorded.
        await store.record_event(topic_events[0])
        assert await store.get_events() == [topic_events[0]]

    @pytest.mark.asyncio
    async def test_recording_is_idempotent(self, topic_events):
        store = EventStoreInMemory(strict=True)
        await store.record_events(topic_events)
        await store.record_events(topic_events + [topic_events[0]])
        assert await store.get_events() == topic_events

    @pytest.mark.asyncio
    async def test_a_datetime_in_invoke_context_kwargs_is_kept_as_iso_text(
        self, topic_events
    ):
        store = EventStoreInMemory(strict=True)
        at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        event = topic_events[0].model_copy(
            update={
                "invoke_context": topic_events[0].invoke_context.model_copy(
                    update={"kwargs": {"at": at}}
                )
            }
        )
        await store.record_event(event)
        [kept] = await store.get_events()
        assert kept.invoke_context.kwargs == {"at": "2026-01-02T03:04:05Z"}

    @pytest.mark.asyncio
    async def test_message_tools_given_as_a_generator_are_kept(self, topic_events):
        store = EventStoreInMemory(strict=True)
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search the web.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        message = Message(role="user", content="hi", tools=(tool for tool in tools))
        event = topic_events[0].model_copy(update={"data": [message]})
        await store.record_event(event)
        [kept] = await store.get_events()
        assert kept == event
        assert kept.data[0].tools == tools

    def test_a_store_is_not_strict_by_default(self):
        assert EventStoreInMemory().strict is False
