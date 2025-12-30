import asyncio
from unittest.mock import Mock

import pytest

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_base import TopicType
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker
from grafi.workflows.impl.async_output_queue import AsyncOutputQueue


class MockOutputTopic(OutputTopic):
    """Mock output topic for testing."""

    def __init__(self, name: str):
        super().__init__(name=name)
        self.type = TopicType.AGENT_OUTPUT_TOPIC_TYPE
        self._events = []
        self._consumed_offset = -1

    async def consume(self, consumer_name: str, timeout: float | None = None):
        """Mock async consume that returns events."""
        if timeout and timeout > 0:
            await asyncio.sleep(timeout)

        # Return events after consumed offset
        new_events = [e for e in self._events if e.offset > self._consumed_offset]
        if new_events:
            self._consumed_offset = new_events[-1].offset
        return new_events

    async def can_consume(self, consumer_name: str) -> bool:
        """Check if there are events to consume."""
        return any(e.offset > self._consumed_offset for e in self._events)

    def add_test_event(self, event: TopicEvent):
        """Add event for testing."""
        self._events.append(event)


class TestAsyncOutputQueue:
    @pytest.fixture
    def tracker(self):
        """Create a mock tracker."""
        return AsyncNodeTracker()

    @pytest.fixture
    def mock_topics(self):
        """Create mock output topics."""
        return [MockOutputTopic("output1"), MockOutputTopic("output2")]

    @pytest.fixture
    def output_queue(self, mock_topics, tracker):
        """Create AsyncOutputQueue instance."""
        return AsyncOutputQueue(mock_topics, "test_consumer", tracker)

    def test_initialization(self, output_queue, mock_topics, tracker):
        """Test proper initialization of AsyncOutputQueue."""
        assert output_queue.output_topics == mock_topics
        assert output_queue.consumer_name == "test_consumer"
        assert output_queue.tracker == tracker
        assert isinstance(output_queue.queue, asyncio.Queue)
        assert output_queue._listener_tasks == []

    @pytest.mark.asyncio
    async def test_start_listeners(self, output_queue, mock_topics):
        """Test starting listener tasks."""
        await output_queue.start_listeners()

        assert len(output_queue._listener_tasks) == len(mock_topics)
        for task in output_queue._listener_tasks:
            assert isinstance(task, asyncio.Task)
            assert not task.done()

        # Clean up
        await output_queue.stop_listeners()

    @pytest.mark.asyncio
    async def test_stop_listeners(self, output_queue):
        """Test stopping listener tasks."""
        await output_queue.start_listeners()
        tasks = output_queue._listener_tasks.copy()

        await output_queue.stop_listeners()

        # All tasks should be cancelled
        for task in tasks:
            assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_output_listener_receives_events(self, mock_topics, tracker):
        """Test that output listener properly receives and queues events."""
        topic = mock_topics[0]
        queue = AsyncOutputQueue([topic], "test_consumer", tracker)

        # Add test event
        test_event = PublishToTopicEvent(
            name="output1",
            publisher_name="test_publisher",
            publisher_type="test_type",
            invoke_context=InvokeContext(
                conversation_id="test", invoke_id="test", assistant_request_id="test"
            ),
            data=[Message(role="assistant", content="test output")],
            consumed_event_ids=[],
            offset=0,
        )
        topic.add_test_event(test_event)

        # Start listener in background
        listener_task = asyncio.create_task(queue._output_listener(topic))

        # Wait a bit for event to be processed
        await asyncio.sleep(0.15)

        # Check event was queued
        assert not queue.queue.empty()
        queued_event = await queue.queue.get()
        assert queued_event == test_event

        # Clean up
        listener_task.cancel()
        await asyncio.gather(listener_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_async_iteration(self, output_queue, mock_topics, tracker):
        """Test async iteration over output events."""
        # Add test event
        test_event = PublishToTopicEvent(
            name="output1",
            publisher_name="test_publisher",
            publisher_type="test_type",
            invoke_context=InvokeContext(
                conversation_id="test", invoke_id="test", assistant_request_id="test"
            ),
            data=[Message(role="assistant", content="test output")],
            consumed_event_ids=[],
            offset=0,
        )

        # Put event directly in queue
        await output_queue.queue.put(test_event)

        # Test iteration
        events = []

        async def collect_events():
            async for event in output_queue:
                events.append(event)
                break  # Only get one event

        # Run with timeout
        await asyncio.wait_for(collect_events(), timeout=0.1)

        assert len(events) == 1
        assert events[0] == test_event

    @pytest.mark.asyncio
    async def test_async_iteration_stops_after_quiescence(self, output_queue, tracker):
        """Async iteration ends when tracker reports quiescence and queue is empty."""
        tracker.on_messages_published(1)
        tracker.on_messages_committed(1)

        events = []
        async for event in output_queue:
            events.append(event)

        assert events == []

    @pytest.mark.asyncio
    async def test_async_iteration_waits_for_quiescence_or_events(self, tracker):
        """__anext__ waits for either new queue data or quiescence signal."""
        queue = AsyncOutputQueue([], "test_consumer", tracker)

        async def signal_quiescence():
            tracker.on_messages_published(1)
            await asyncio.sleep(0.02)
            tracker.on_messages_committed(1)

        signal_task = asyncio.create_task(signal_quiescence())

        events = []
        async for event in queue:
            events.append(event)

        await signal_task
        assert events == []

    @pytest.mark.asyncio
    async def test_event_emitted_before_quiescence(self, tracker):
        """Events in the queue are yielded even if quiescence follows immediately."""
        queue = AsyncOutputQueue([], "test_consumer", tracker)
        queued_event = Mock()
        queued_event.name = "queued_event"
        await queue.queue.put(queued_event)

        tracker.on_messages_published(1)
        tracker.on_messages_committed(1)

        events = []
        async for event in queue:
            events.append(event)
        assert [e.name for e in events] == ["queued_event"]

    @pytest.mark.asyncio
    async def test_type_annotations(self, output_queue):
        """Test that type annotations are correct."""
        # Test __aiter__ returns AsyncGenerator[TopicEvent, None]
        aiter = output_queue.__aiter__()
        assert aiter == output_queue

        # Test queue type
        assert isinstance(output_queue.queue, asyncio.Queue)

    @pytest.mark.asyncio
    async def test_concurrent_listeners(self, tracker):
        """Test multiple listeners working concurrently."""
        # Create multiple topics
        topics = [MockOutputTopic(f"output{i}") for i in range(3)]
        queue = AsyncOutputQueue(topics, "test_consumer", tracker)

        # Add events to different topics
        for i, topic in enumerate(topics):
            event = PublishToTopicEvent(
                name=f"output{i}",
                publisher_name="test_publisher",
                publisher_type="test_type",
                invoke_context=InvokeContext(
                    conversation_id="test",
                    invoke_id="test",
                    assistant_request_id="test",
                ),
                data=[Message(role="assistant", content=f"output {i}")],
                consumed_event_ids=[],
                offset=i,
            )
            topic.add_test_event(event)

        # Start listeners
        await queue.start_listeners()

        # Collect events
        collected = []
        try:
            # Add activity to prevent idle exit
            await tracker.enter("test_node")

            # Wait for events
            for _ in range(3):
                event = await asyncio.wait_for(queue.queue.get(), timeout=0.5)
                collected.append(event)
        finally:
            await tracker.leave("test_node")
            await queue.stop_listeners()

        # Should have collected all events
        assert len(collected) == 3
        assert all(isinstance(e, PublishToTopicEvent) for e in collected)

    @pytest.mark.asyncio
    async def test_anext_waits_for_activity_count_stabilization(self):
        """
        Test that __anext__ doesn't prematurely terminate when activity count changes.

        This tests the race condition fix where the output queue could terminate
        before downstream nodes finish processing.
        """
        tracker = AsyncNodeTracker()

        output_queue = AsyncOutputQueue(
            output_topics=[],  # Empty - we'll put events directly in queue
            consumer_name="test_consumer",
            tracker=tracker,
        )

        # Simulate: node enters, adds item to queue, leaves
        # Then another node should enter before we terminate

        async def simulate_node_activity():
            """Simulate node activity that should prevent premature termination."""
            # First node processes - simulate full message lifecycle
            tracker.on_messages_published(1)
            await tracker.enter("node_1")
            await output_queue.queue.put(Mock(name="event_1"))
            await tracker.leave("node_1")
            tracker.on_messages_committed(1)

            # Yield control - simulates realistic timing where next node
            # starts within the same event loop cycle
            await asyncio.sleep(0)

            # Second node picks up and processes - simulate full message lifecycle
            tracker.on_messages_published(1)
            await tracker.enter("node_2")
            await output_queue.queue.put(Mock(name="event_2"))
            await tracker.leave("node_2")
            tracker.on_messages_committed(1)

        # Start the activity simulation
        activity_task = asyncio.create_task(simulate_node_activity())

        # Iterate over the queue
        events = []
        async for event in output_queue:
            events.append(event)
            if len(events) >= 2:
                break

        await activity_task

        # Should have received both events
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_anext_terminates_when_truly_idle(self):
        """
        Test that __anext__ correctly terminates when no more activity.
        """
        tracker = AsyncNodeTracker()

        output_queue = AsyncOutputQueue(
            output_topics=[],  # Empty - we'll put events directly in queue
            consumer_name="test_consumer",
            tracker=tracker,
        )

        # Single node processes and finishes - simulate full message lifecycle
        async def simulate_single_node():
            tracker.on_messages_published(1)
            await tracker.enter("node_1")
            await output_queue.queue.put(Mock(name="event_1"))
            await tracker.leave("node_1")
            tracker.on_messages_committed(1)

        activity_task = asyncio.create_task(simulate_single_node())

        events = []
        async for event in output_queue:
            events.append(event)

        await activity_task

        # Should terminate after receiving the single event
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_activity_count_prevents_premature_exit(self):
        """
        Test specifically that activity count tracking prevents race condition.

        Scenario:
        1. Node A finishes and tracker goes idle
        2. __anext__ sees idle but activity count changed
        3. Node B starts before __anext__ decides to terminate
        4. All events are properly yielded
        """
        tracker = AsyncNodeTracker()

        output_queue = AsyncOutputQueue(
            output_topics=[],  # Empty - we'll put events directly in queue
            consumer_name="test_consumer",
            tracker=tracker,
        )

        events_received = []
        iteration_complete = asyncio.Event()

        async def consumer():
            async for event in output_queue:
                events_received.append(event)
            iteration_complete.set()

        async def producer():
            # Node A processes - simulate full message lifecycle
            tracker.on_messages_published(1)
            await tracker.enter("node_a")
            await output_queue.queue.put(Mock(name="event_a"))
            await tracker.leave("node_a")
            tracker.on_messages_committed(1)

            # Critical timing window - yield to let consumer check idle state
            await asyncio.sleep(0)

            # Node B starts before consumer terminates (if fix works)
            # simulate full message lifecycle
            tracker.on_messages_published(1)
            await tracker.enter("node_b")
            await output_queue.queue.put(Mock(name="event_b"))
            await tracker.leave("node_b")
            tracker.on_messages_committed(1)

        consumer_task = asyncio.create_task(consumer())
        producer_task = asyncio.create_task(producer())

        # Wait for producer to finish
        await producer_task

        # Wait a bit for consumer to process
        try:
            await asyncio.wait_for(iteration_complete.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass

        # With the fix, we should receive both events
        assert len(events_received) == 2, (
            f"Expected 2 events but got {len(events_received)}. "
            "Race condition may have caused premature termination."
        )

    @pytest.mark.asyncio
    async def test_force_stop_terminates_iteration(self):
        """
        Test that force_stop terminates iteration even with uncommitted messages.
        """
        tracker = AsyncNodeTracker()
        output_queue = AsyncOutputQueue(
            output_topics=[],
            consumer_name="test_consumer",
            tracker=tracker,
        )

        # Publish messages but don't commit them (simulates incomplete work)
        tracker.on_messages_published(5)

        # Not quiescent because uncommitted > 0
        assert not tracker.is_quiescent
        assert tracker.get_metrics()["uncommitted_messages"] == 5

        # Start iteration in background
        events = []
        iteration_complete = asyncio.Event()

        async def iterate():
            async for event in output_queue:
                events.append(event)
            iteration_complete.set()

        iteration_task = asyncio.create_task(iterate())

        # Give iteration a chance to start waiting
        await asyncio.sleep(0.05)

        # Force stop should terminate iteration
        tracker.force_stop()

        # Wait for iteration to complete
        try:
            await asyncio.wait_for(iteration_complete.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            iteration_task.cancel()
            pytest.fail("Force stop did not terminate iteration within timeout")

        await iteration_task
        assert events == []

    @pytest.mark.asyncio
    async def test_force_stop_yields_queued_events_before_terminating(self):
        """
        Test that force_stop yields any queued events before terminating.
        """
        tracker = AsyncNodeTracker()
        output_queue = AsyncOutputQueue(
            output_topics=[],
            consumer_name="test_consumer",
            tracker=tracker,
        )

        # Simulate work with uncommitted messages
        tracker.on_messages_published(5)

        # Queue some events
        await output_queue.queue.put(Mock(name="event_1"))
        await output_queue.queue.put(Mock(name="event_2"))

        events = []
        iteration_complete = asyncio.Event()

        async def iterate():
            async for event in output_queue:
                events.append(event)
            iteration_complete.set()

        iteration_task = asyncio.create_task(iterate())

        # Give iteration a chance to get the queued events
        await asyncio.sleep(0.05)

        # Force stop
        tracker.force_stop()

        # Wait for iteration to complete
        await asyncio.wait_for(iteration_complete.wait(), timeout=1.0)
        await iteration_task

        # Should have received the queued events before terminating
        assert len(events) == 2
