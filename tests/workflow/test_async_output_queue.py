import asyncio

import pytest

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.output_topic import OutputTopic
from grafi.topics.topic_base import TopicType
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker
from grafi.workflows.impl.async_output_queue import AsyncOutputQueue


class MockOutputTopic(OutputTopic):
    """Mock output topic for testing."""

    def __init__(self, name: str):
        super().__init__(name=name)
        self.type = TopicType.AGENT_OUTPUT_TOPIC_TYPE
        self._events = []
        self._consumed_offset = -1

    async def a_consume(self, consumer_name: str):
        """Mock async consume that returns events."""
        # Simulate waiting for events
        await asyncio.sleep(0.01)

        # Return events after consumed offset
        new_events = [e for e in self._events if e.offset > self._consumed_offset]
        if new_events:
            self._consumed_offset = new_events[-1].offset
        return new_events

    def can_consume(self, consumer_name: str) -> bool:
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
        assert output_queue.listener_tasks == []

    @pytest.mark.asyncio
    async def test_start_listeners(self, output_queue, mock_topics):
        """Test starting listener tasks."""
        await output_queue.start_listeners()

        assert len(output_queue.listener_tasks) == len(mock_topics)
        for task in output_queue.listener_tasks:
            assert isinstance(task, asyncio.Task)
            assert not task.done()

        # Clean up
        await output_queue.stop_listeners()

    @pytest.mark.asyncio
    async def test_stop_listeners(self, output_queue):
        """Test stopping listener tasks."""
        await output_queue.start_listeners()
        tasks = output_queue.listener_tasks.copy()

        await output_queue.stop_listeners()

        # All tasks should be cancelled
        for task in tasks:
            assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_output_listener_receives_events(self, mock_topics, tracker):
        """Test that output listener properly receives and queues events."""
        topic = mock_topics[0]
        queue = AsyncOutputQueue([topic], "test_consumer", tracker)

        # Add activity to prevent listener from exiting
        await tracker.enter("test_node")

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
        await asyncio.sleep(0.05)

        # Check event was queued
        assert not queue.queue.empty()
        queued_event = await queue.queue.get()
        assert queued_event == test_event

        # Clean up
        await tracker.leave("test_node")
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
    async def test_async_iteration_stops_on_idle(self, output_queue, tracker):
        """Test that async iteration stops when tracker is idle and queue is empty."""
        # Make tracker idle
        assert tracker.is_idle()

        # Ensure queue is empty
        assert output_queue.queue.empty()

        # Iteration should stop
        events = []
        async for event in output_queue:
            events.append(event)

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_listener_exits_on_idle_and_no_data(self, mock_topics, tracker):
        """Test that listener exits when workflow is idle and no more data."""
        topic = mock_topics[0]
        queue = AsyncOutputQueue([topic], "test_consumer", tracker)

        # Ensure tracker is idle
        assert tracker.is_idle()

        # Run listener - should exit quickly since idle and no data
        await queue._output_listener(topic)

        # Should complete without hanging
        assert True

    @pytest.mark.asyncio
    async def test_listener_continues_with_activity(self, mock_topics, tracker):
        """Test that listener continues when there's activity."""
        topic = mock_topics[0]
        queue = AsyncOutputQueue([topic], "test_consumer", tracker)

        # Add activity
        await tracker.enter("node1")

        # Start listener
        listener_task = asyncio.create_task(queue._output_listener(topic))

        # Should still be running
        await asyncio.sleep(0.05)
        assert not listener_task.done()

        # Clean up
        listener_task.cancel()
        await asyncio.gather(listener_task, return_exceptions=True)
        await tracker.leave("node1")

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
