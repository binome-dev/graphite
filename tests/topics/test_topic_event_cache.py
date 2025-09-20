import asyncio
from datetime import datetime

import pytest

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue
from grafi.topics.queue_impl.in_mem_topic_event_queue import TopicEventQueue


class TestTopicEventQueue:
    @pytest.fixture
    def cache(self):
        return InMemTopicEventQueue()

    @pytest.fixture
    def sample_event(self):
        invoke_context = InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )
        return PublishToTopicEvent(
            event_id="event-1",
            name="test_topic",
            offset=0,
            publisher_name="test_publisher",
            publisher_type="test_type",
            consumed_event_ids=[],
            invoke_context=invoke_context,
            data=[Message(role="user", content="test message")],
            timestamp=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_initialization(self):
        cache = InMemTopicEventQueue()
        assert cache._records == []
        assert len(cache._consumed) == 0
        assert len(cache._committed) == 0

    @pytest.mark.asyncio
    async def test_reset(self, cache: TopicEventQueue, sample_event):
        # Add some data
        await cache.a_put(sample_event)
        cache._consumed["consumer1"] = 1
        cache._committed["consumer1"] = 0

        # Reset
        await cache.a_reset()

        # Verify everything is cleared
        assert cache._records == []
        assert len(cache._consumed) == 0
        assert len(cache._committed) == 0

    @pytest.mark.asyncio
    async def test_put(self, cache: TopicEventQueue, sample_event):
        # Put an event
        result = await cache.a_put(sample_event)

        assert result == sample_event
        assert cache._records[0] == sample_event

    def test_ensure_consumer(self, cache: TopicEventQueue):
        # Initially no consumers
        assert "consumer1" not in cache._consumed
        assert "consumer1" not in cache._committed

        # Verify consumer is initialized
        assert cache._consumed["consumer1"] == 0
        assert cache._committed["consumer1"] == -1

    @pytest.mark.asyncio
    async def test_can_consume_no_events(self, cache: TopicEventQueue):
        # No events, so can't consume
        assert not await cache.a_can_consume("consumer1")

    @pytest.mark.asyncio
    async def test_can_consume_with_events(self, cache: TopicEventQueue, sample_event):
        await cache.a_put(sample_event)

        # New consumer can consume
        assert await cache.a_can_consume("consumer1")

        # After consuming, can't consume anymore
        await cache.a_fetch("consumer1", timeout=0.1)
        assert not await cache.a_can_consume("consumer1")

    @pytest.mark.asyncio
    async def test_fetch_no_events(self, cache: TopicEventQueue):
        # Fetch with no events returns empty list
        result = await cache.a_fetch("consumer1", timeout=0.1)
        assert result == []  # Returns empty list when no events to consume

    @pytest.mark.asyncio
    async def test_fetch_single_event(self, cache: TopicEventQueue, sample_event):
        await cache.a_put(sample_event)

        # Fetch event
        result = await cache.a_fetch("consumer1")
        assert result == [sample_event]
        assert cache._consumed["consumer1"] == 1

        # Can't fetch again
        result = await cache.a_fetch("consumer1", timeout=0.1)
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_multiple_events(self, cache: TopicEventQueue):
        # Create multiple events
        events = []
        for i in range(5):
            invoke_context = InvokeContext(
                conversation_id="test-conversation",
                invoke_id=f"test-invoke-{i}",
                assistant_request_id="test-request",
            )
            event = PublishToTopicEvent(
                event_id=f"event-{i}",
                name="test_topic",
                offset=i,
                publisher_name="test_publisher",
                publisher_type="test_type",
                consumed_event_ids=[],
                invoke_context=invoke_context,
                data=[Message(role="user", content=f"message {i}")],
                timestamp=datetime.now(),
            )
            events.append(event)
            await cache.a_put(event)

        # Fetch all events
        result = await cache.a_fetch("consumer1", timeout=0.1)
        assert result == events
        assert cache._consumed["consumer1"] == 5

    @pytest.mark.asyncio
    async def test_fetch_with_offset(self, cache: TopicEventQueue):
        # Add 5 events
        events = []
        for i in range(5):
            invoke_context = InvokeContext(
                conversation_id="test-conversation",
                invoke_id=f"test-invoke-{i}",
                assistant_request_id="test-request",
            )
            event = PublishToTopicEvent(
                event_id=f"event-{i}",
                name="test_topic",
                offset=i,
                publisher_name="test_publisher",
                publisher_type="test_type",
                consumed_event_ids=[],
                invoke_context=invoke_context,
                data=[Message(role="user", content=f"message {i}")],
                timestamp=datetime.now(),
            )
            events.append(event)
            await cache.a_put(event)

        # Fetch only up to offset 3
        result = await cache.a_fetch("consumer1", offset=3, timeout=0.1)
        assert len(result) == 4
        assert result == events[:4]
        assert cache._consumed["consumer1"] == 4

        # Fetch remaining
        result = await cache.a_fetch("consumer1", timeout=0.1)
        assert len(result) == 1
        assert result == events[4:]

    @pytest.mark.asyncio
    async def test_multiple_consumers(self, cache: TopicEventQueue, sample_event):
        await cache.a_put(sample_event)

        # Both consumers can fetch the same event
        result1 = await cache.a_fetch("consumer1", timeout=0.1)
        result2 = await cache.a_fetch("consumer2", timeout=0.1)

        assert result1 == [sample_event]
        assert result2 == [sample_event]
        assert cache._consumed["consumer1"] == 1
        assert cache._consumed["consumer2"] == 1

    @pytest.mark.asyncio
    async def test_commit_to(self, cache: TopicEventQueue):
        # Commit for a consumer
        result = await cache.a_commit_to("consumer1", 5)
        assert result == 5
        assert cache._committed["consumer1"] == 5

        # Update commit
        result = await cache.a_commit_to("consumer1", 10)
        assert result == 10
        assert cache._committed["consumer1"] == 10

    @pytest.mark.asyncio
    async def test_a_put(self, cache: TopicEventQueue, sample_event):
        # Put event asynchronously
        result = await cache.a_put(sample_event)

        assert result == sample_event
        assert cache._records[0] == sample_event

    @pytest.mark.asyncio
    async def test_a_fetch_no_events_with_timeout(self, cache: TopicEventQueue):
        # Try to fetch with timeout when no events
        result = await cache.a_fetch("consumer1", timeout=0.1)
        assert result == []

    @pytest.mark.asyncio
    async def test_a_fetch_single_event(self, cache: TopicEventQueue, sample_event):
        await cache.a_put(sample_event)

        # Fetch event
        result = await cache.a_fetch("consumer1", timeout=0.1)
        assert result == [sample_event]
        assert cache._consumed["consumer1"] == 1

    @pytest.mark.asyncio
    async def test_a_fetch_wait_for_event(self, cache: TopicEventQueue, sample_event):
        # Start fetch task that will wait
        fetch_task = asyncio.create_task(cache.a_fetch("consumer1", timeout=1.0))

        # Give it time to start waiting
        await asyncio.sleep(0.1)

        # Put event
        await cache.a_put(sample_event)

        # Fetch should complete with the event
        result = await fetch_task
        assert result == [sample_event]

    @pytest.mark.asyncio
    async def test_a_fetch_with_offset(self, cache: TopicEventQueue):
        # Add 5 events
        events = []
        for i in range(5):
            invoke_context = InvokeContext(
                conversation_id="test-conversation",
                invoke_id=f"test-invoke-{i}",
                assistant_request_id="test-request",
            )
            event = PublishToTopicEvent(
                event_id=f"event-{i}",
                name="test_topic",
                offset=i,
                publisher_name="test_publisher",
                publisher_type="test_type",
                consumed_event_ids=[],
                invoke_context=invoke_context,
                data=[Message(role="user", content=f"message {i}")],
                timestamp=datetime.now(),
            )
            events.append(event)
            await cache.a_put(event)

        # Fetch only up to offset 3
        result = await cache.a_fetch("consumer1", offset=3, timeout=0.1)
        assert len(result) == 4
        assert result == events[:4]

    @pytest.mark.asyncio
    async def test_a_commit_to(self, cache: TopicEventQueue):
        # Commit asynchronously
        await cache.a_commit_to("consumer1", 5)
        assert cache._committed["consumer1"] == 5

    @pytest.mark.asyncio
    async def test_concurrent_producers(self, cache: TopicEventQueue):
        # Multiple producers adding events concurrently
        async def producer(producer_id: int, count: int):
            for i in range(count):
                invoke_context = InvokeContext(
                    conversation_id="test-conversation",
                    invoke_id=f"producer-{producer_id}-invoke-{i}",
                    assistant_request_id="test-request",
                )
                event = PublishToTopicEvent(
                    event_id=f"producer-{producer_id}-event-{i}",
                    name="test_topic",
                    offset=i,
                    publisher_name=f"producer-{producer_id}",
                    publisher_type="test_type",
                    consumed_event_ids=[],
                    invoke_context=invoke_context,
                    data=[
                        Message(
                            role="user", content=f"producer {producer_id} message {i}"
                        )
                    ],
                    timestamp=datetime.now(),
                )
                await cache.a_put(event)

        # Run 3 producers concurrently
        await asyncio.gather(
            producer(1, 5),
            producer(2, 5),
            producer(3, 5),
        )

        # Should have 15 events total
        assert len(await cache.a_fetch("temp_id", timeout=0.1)) == 15

    @pytest.mark.asyncio
    async def test_concurrent_consumers(self, cache: TopicEventQueue):
        # Add 10 events
        for i in range(10):
            invoke_context = InvokeContext(
                conversation_id="test-conversation",
                invoke_id=f"test-invoke-{i}",
                assistant_request_id="test-request",
            )
            event = PublishToTopicEvent(
                event_id=f"event-{i}",
                name="test_topic",
                offset=i,
                publisher_name="test_publisher",
                publisher_type="test_type",
                consumed_event_ids=[],
                invoke_context=invoke_context,
                data=[Message(role="user", content=f"message {i}")],
                timestamp=datetime.now(),
            )
            await cache.a_put(event)

        # Multiple consumers fetching concurrently
        async def consumer(consumer_id: str):
            all_events = []
            while True:
                events = await cache.a_fetch(consumer_id, timeout=0.1)
                if not events:
                    break
                all_events.extend(events)
            return all_events

        # Run 3 consumers concurrently
        results = await asyncio.gather(
            consumer("consumer1"),
            consumer("consumer2"),
            consumer("consumer3"),
        )

        # Each consumer should get all 10 events
        for result in results:
            assert len(result) == 10

    @pytest.mark.asyncio
    async def test_producer_consumer_pipeline(self, cache: TopicEventQueue):
        # Test a producer-consumer pipeline
        produced_events = []
        consumed_events = []

        async def producer():
            for i in range(5):
                invoke_context = InvokeContext(
                    conversation_id="test-conversation",
                    invoke_id=f"test-invoke-{i}",
                    assistant_request_id="test-request",
                )
                event = PublishToTopicEvent(
                    event_id=f"event-{i}",
                    name="test_topic",
                    offset=i,
                    publisher_name="producer",
                    publisher_type="test_type",
                    consumed_event_ids=[],
                    invoke_context=invoke_context,
                    data=[Message(role="user", content=f"message {i}")],
                    timestamp=datetime.now(),
                )
                produced_events.append(event)
                await cache.a_put(event)
                await asyncio.sleep(0.05)  # Simulate production delay

        async def consumer():
            while len(consumed_events) < 5:
                events = await cache.a_fetch("consumer", timeout=0.5)
                consumed_events.extend(events)
                if events:
                    # Commit after consuming
                    await cache.a_commit_to("consumer", cache._consumed["consumer"] - 1)

        # Run producer and consumer concurrently
        await asyncio.gather(producer(), consumer())

        # Verify all events were consumed
        assert len(consumed_events) == 5
        assert consumed_events == produced_events
        assert cache._committed["consumer"] == 4  # Last offset is 4 (0-indexed)

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_list_when_no_events_available(
        self, cache: TopicEventQueue
    ):
        # When can_consume returns False, fetch should return empty list
        assert await cache.a_fetch("consumer1", timeout=0.1) == []

    @pytest.mark.asyncio
    async def test_consumer_isolation(self, cache: TopicEventQueue):
        # Add events
        events = []
        for i in range(3):
            invoke_context = InvokeContext(
                conversation_id="test-conversation",
                invoke_id=f"test-invoke-{i}",
                assistant_request_id="test-request",
            )
            event = PublishToTopicEvent(
                event_id=f"event-{i}",
                name="test_topic",
                offset=i,
                publisher_name="test_publisher",
                publisher_type="test_type",
                consumed_event_ids=[],
                invoke_context=invoke_context,
                data=[Message(role="user", content=f"message {i}")],
                timestamp=datetime.now(),
            )
            events.append(event)
            await cache.a_put(event)

        # Consumer 1 fetches first 2 events
        result1 = await cache.a_fetch("consumer1", offset=2)
        assert len(result1) == 3
        assert cache._consumed["consumer1"] == 3

        # Consumer 2 can still fetch all events
        result2 = await cache.a_fetch("consumer2")
        assert len(result2) == 3
        assert cache._consumed["consumer2"] == 3

    @pytest.mark.asyncio
    async def test_commit_before_consume(self, cache: TopicEventQueue):
        # Commit before any consumption
        result = await cache.a_commit_to("consumer1", 10)
        assert result == 10
        assert cache._committed["consumer1"] == 10
        assert cache._consumed["consumer1"] == 0  # Still at 0

    @pytest.mark.asyncio
    async def test_multiple_waiters(self, cache: TopicEventQueue):
        # Multiple consumers waiting for events
        fetch_tasks = [
            asyncio.create_task(cache.a_fetch("consumer1", timeout=1.0)),
            asyncio.create_task(cache.a_fetch("consumer2", timeout=1.0)),
            asyncio.create_task(cache.a_fetch("consumer3", timeout=1.0)),
        ]

        # Give them time to start waiting
        await asyncio.sleep(0.1)

        # Add an event
        invoke_context = InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )
        event = PublishToTopicEvent(
            event_id="event-1",
            name="test_topic",
            offset=0,
            publisher_name="test_publisher",
            publisher_type="test_type",
            consumed_event_ids=[],
            invoke_context=invoke_context,
            data=[Message(role="user", content="test message")],
            timestamp=datetime.now(),
        )
        await cache.a_put(event)

        # All consumers should get the event
        results = await asyncio.gather(*fetch_tasks)
        for result in results:
            assert len(result) == 1
            assert result[0] == event

    @pytest.mark.asyncio
    async def test_fetch_with_offset_boundary_cases(self, cache: TopicEventQueue):
        # Add 5 events
        events = []
        for i in range(5):
            invoke_context = InvokeContext(
                conversation_id="test-conversation",
                invoke_id=f"test-invoke-{i}",
                assistant_request_id="test-request",
            )
            event = PublishToTopicEvent(
                event_id=f"event-{i}",
                name="test_topic",
                offset=i,
                publisher_name="test_publisher",
                publisher_type="test_type",
                consumed_event_ids=[],
                invoke_context=invoke_context,
                data=[Message(role="user", content=f"message {i}")],
                timestamp=datetime.now(),
            )
            events.append(event)
            await cache.a_put(event)

        # Test offset = 0 (should return empty since start=0, end=max(0,0)=0)
        result = await cache.a_fetch("consumer1", offset=0)
        assert len(result) == 1
        assert cache._consumed["consumer1"] == 1

        # Test offset equal to current position
        cache._consumed["consumer1"] = 2
        result = await cache.a_fetch("consumer1", offset=2)
        assert len(result) == 1  # start=2, end=max(2,2)=2, so slice[2:2] is empty

        # Test offset less than current position (should still use current position)
        cache._consumed["consumer1"] = 3
        result = await cache.a_fetch("consumer1", offset=1, timeout=0.1)
        assert len(result) == 0  # start=3, end=max(3,1)=3, so slice[3:3] is empty

        # Test offset greater than available events
        cache._consumed["consumer1"] = 1
        result = await cache.a_fetch("consumer1", offset=10)
        assert len(result) == 4  # Should get all 4 events
        assert cache._consumed["consumer1"] == 5
