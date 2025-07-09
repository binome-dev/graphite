import asyncio
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_async_event import OutputAsyncEvent
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.output_topic import AGENT_OUTPUT_TOPIC
from grafi.common.topics.output_topic import OutputTopic
from grafi.common.topics.output_topic import OutputTopicBuilder
from grafi.common.topics.output_topic import agent_output_topic


class TestOutputTopic:
    @pytest.fixture
    def sample_invoke_context(self):
        return InvokeContext(
            user_id="test_user",
            conversation_id="test_conversation",
            invoke_id="test_invoke",
            assistant_request_id="test_assistant_request",
        )

    @pytest.fixture
    def sample_messages(self):
        return [
            Message(content="Hello", role="user"),
            Message(content="Hi there!", role="assistant"),
        ]

    @pytest.fixture
    def sample_consumed_events(self):
        return [
            ConsumeFromTopicEvent(
                event_id="test_id_1",
                event_type="ConsumeFromTopic",
                timestamp="2009-02-13T23:31:30+00:00",
                topic_name="test_topic",
                consumer_name="test_node",
                consumer_type="test_type",
                offset=0,
                invoke_context=InvokeContext(
                    user_id="test_user",
                    conversation_id="test_conversation",
                    invoke_id="test_invoke",
                    assistant_request_id="test_assistant_request",
                ),
                data=[
                    Message(
                        message_id="ea72df51439b42e4a43b217c9bca63f5",
                        timestamp=1737138526189505000,
                        role="user",
                        content="Hello, my name is Grafi, how are you doing?",
                        name=None,
                        functions=None,
                        function_call=None,
                    )
                ],
            ),
            ConsumeFromTopicEvent(
                event_id="test_id_2",
                event_type="ConsumeFromTopic",
                timestamp="2009-02-13T23:31:30+00:00",
                topic_name="test_topic",
                consumer_name="test_node",
                consumer_type="test_type",
                offset=0,
                invoke_context=InvokeContext(
                    conversation_id="conversation_id",
                    invoke_id="invoke_id",
                    assistant_request_id="assistant_request_id",
                ),
                data=[
                    Message(
                        message_id="ea72df51439b42e4a43b217c9bca63f5",
                        timestamp=1737138526189505000,
                        role="user",
                        content="Hello, my name is Grafi, how are you doing?",
                        name=None,
                        functions=None,
                        function_call=None,
                    )
                ],
            ),
        ]

    @pytest.fixture
    def output_topic(self):
        topic = OutputTopic(name="test_output_topic")
        yield topic
        # Cleanup after test
        topic.reset()

    def test_output_topic_creation(self):
        """Test creating an OutputTopic with default values."""
        topic = OutputTopic()

        assert topic.name == AGENT_OUTPUT_TOPIC
        assert isinstance(topic.event_queue, asyncio.Queue)
        assert topic.active_generators == []
        assert topic.publish_event_handler is None

    def test_output_topic_with_custom_name(self):
        """Test creating an OutputTopic with custom name."""
        topic = OutputTopic(name="custom_topic")

        assert topic.name == "custom_topic"

    def test_builder_pattern(self):
        """Test using the builder pattern to create OutputTopic."""
        builder = OutputTopic.builder()
        assert isinstance(builder, OutputTopicBuilder)

        topic = builder.build()
        assert isinstance(topic, OutputTopic)

    def test_builder_with_publish_event_handler(self):
        """Test builder with publish event handler."""
        handler = Mock()

        topic = OutputTopic.builder().publish_event_handler(handler).build()

        assert topic.publish_event_handler == handler

    def test_reset(self, output_topic):
        """Test resetting the topic state."""
        # Add some mock tasks
        mock_task1 = Mock()
        mock_task1.done.return_value = False
        mock_task2 = Mock()
        mock_task2.done.return_value = True

        output_topic.active_generators = [mock_task1, mock_task2]
        # Add some events to the cache to test reset
        output_topic.event_cache.put(0, Mock())
        output_topic.event_cache.put(1, Mock())

        output_topic.reset()

        # Check that incomplete tasks were cancelled
        mock_task1.cancel.assert_called_once()
        mock_task2.cancel.assert_not_called()

        # Check that collections were cleared
        assert output_topic.active_generators == []
        assert len(output_topic.event_cache) == 0
        assert isinstance(output_topic.event_queue, asyncio.Queue)

    def test_publish_data_with_condition_true(
        self,
        output_topic,
        sample_invoke_context,
        sample_messages,
        sample_consumed_events,
    ):
        """Test publishing data when condition is met."""
        # Mock condition to return True
        output_topic.condition = Mock(return_value=True)

        event = output_topic.publish_data(
            invoke_context=sample_invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=sample_messages,
            consumed_events=sample_consumed_events,
        )

        assert event is not None
        assert isinstance(event, OutputTopicEvent)
        assert event.publisher_name == "test_publisher"
        assert event.publisher_type == "test_type"
        assert event.data == sample_messages
        assert event.consumed_event_ids == ["test_id_1", "test_id_2"]
        assert event.offset == 0
        assert len(output_topic.event_cache) == 1

    def test_publish_data_with_condition_false(
        self,
        output_topic,
        sample_invoke_context,
        sample_messages,
        sample_consumed_events,
    ):
        """Test publishing data when condition is not met."""
        # Mock condition to return False
        output_topic.condition = Mock(return_value=False)

        event = output_topic.publish_data(
            invoke_context=sample_invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=sample_messages,
            consumed_events=sample_consumed_events,
        )

        assert event is None
        assert len(output_topic.event_cache) == 0

    def test_publish_data_with_event_handler(
        self,
        output_topic,
        sample_invoke_context,
        sample_messages,
        sample_consumed_events,
    ):
        """Test publishing data with event handler."""
        handler = Mock()
        output_topic.publish_event_handler = handler
        output_topic.condition = Mock(return_value=True)

        event = output_topic.publish_data(
            invoke_context=sample_invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=sample_messages,
            consumed_events=sample_consumed_events,
        )

        handler.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_add_generator(self, output_topic, sample_invoke_context):
        """Test adding a generator to the topic."""

        async def mock_generator():
            yield [Message(content="test", role="assistant")]

        with patch.object(output_topic, "_process_generator") as mock_process:
            mock_process.return_value = asyncio.create_task(asyncio.sleep(0))

            output_topic.add_generator(
                generator=mock_generator(),
                data=[],
                invoke_context=sample_invoke_context,
                publisher_name="test_publisher",
                publisher_type="test_type",
            )

            assert len(output_topic.active_generators) == 1
            assert isinstance(output_topic.active_generators[0], asyncio.Task)

    @pytest.mark.asyncio
    async def test_process_generator_success(self, output_topic, sample_invoke_context):
        """Test successful processing of a generator."""
        messages1 = [Message(content="Hello", role="assistant")]
        messages2 = [Message(content=" World", role="assistant")]

        async def mock_generator():
            yield messages1
            yield messages2

        with patch(
            "grafi.common.containers.container.container.event_store.record_event"
        ) as mock_record:
            await output_topic._process_generator(
                generator=mock_generator(),
                data=[],
                invoke_context=sample_invoke_context,
                publisher_name="test_publisher",
                publisher_type="test_type",
                consumed_events=[],
            )

            # Check that events were queued
            events = []
            while not output_topic.event_queue.empty():
                events.append(output_topic.event_queue.get_nowait())

            assert len(events) == 2
            assert all(isinstance(event, OutputAsyncEvent) for event in events)

            # Check that final event was recorded
            mock_record.assert_called_once()
            recorded_event = mock_record.call_args[0][0]
            assert isinstance(recorded_event, OutputTopicEvent)
            assert recorded_event.data[0].content == "Hello World"

    @pytest.mark.asyncio
    async def test_process_generator_cancelled(
        self, output_topic, sample_invoke_context
    ):
        """Test generator processing when cancelled."""

        async def mock_generator():
            while True:
                yield [Message(content="test", role="assistant")]
                await asyncio.sleep(0.1)

        task = asyncio.create_task(
            output_topic._process_generator(
                generator=mock_generator(),
                data=[],
                invoke_context=sample_invoke_context,
                publisher_name="test_publisher",
                publisher_type="test_type",
                consumed_events=[],
            )
        )

        # Cancel the task
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_process_generator_exception(
        self, output_topic, sample_invoke_context
    ):
        """Test generator processing when an exception occurs."""

        async def failing_generator():
            yield [Message(content="test", role="assistant")]
            raise ValueError("Test error")

        # Should not raise exception, but handle it internally
        await output_topic._process_generator(
            generator=failing_generator(),
            data=[],
            invoke_context=sample_invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            consumed_events=[],
        )

        # Should have one event queued before the error
        assert not output_topic.event_queue.empty()

    @pytest.mark.asyncio
    async def test_get_events_with_active_generators(self, output_topic):
        """Test getting events while generators are active."""
        # Mock some events in the queue
        event1 = Mock(spec=OutputAsyncEvent)
        event2 = Mock(spec=OutputAsyncEvent)

        await output_topic.event_queue.put(event1)
        await output_topic.event_queue.put(event2)

        # Mock an active generator that will finish
        mock_task = Mock()
        mock_task.done.return_value = True
        output_topic.active_generators = [mock_task]

        events = []
        async for event in output_topic.get_events():
            events.append(event)

        assert len(events) == 2
        assert events[0] == event1
        assert events[1] == event2

    @pytest.mark.asyncio
    async def test_get_events_no_active_generators(self, output_topic):
        """Test getting events when no generators are active."""
        # Mock some events in the queue
        event1 = Mock(spec=OutputAsyncEvent)
        event2 = Mock(spec=OutputAsyncEvent)

        await output_topic.event_queue.put(event1)
        await output_topic.event_queue.put(event2)

        # No active generators
        output_topic.active_generators = []

        events = []
        async for event in output_topic.get_events():
            events.append(event)

        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_wait_for_completion(self, output_topic):
        """Test waiting for all generators to complete."""
        # Create mock tasks
        task1 = asyncio.create_task(asyncio.sleep(0.01))
        task2 = asyncio.create_task(asyncio.sleep(0.02))

        output_topic.active_generators = [task1, task2]

        await output_topic.wait_for_completion()

        assert task1.done()
        assert task2.done()

    @pytest.mark.asyncio
    async def test_wait_for_completion_with_exceptions(self, output_topic):
        """Test waiting for completion when tasks raise exceptions."""

        async def failing_task():
            raise ValueError("Test error")

        task1 = asyncio.create_task(failing_task())
        task2 = asyncio.create_task(asyncio.sleep(0.01))

        output_topic.active_generators = [task1, task2]

        # Should not raise exception due to return_exceptions=True
        await output_topic.wait_for_completion()

        assert task1.done()
        assert task2.done()

    def test_global_agent_output_topic(self):
        """Test the global agent_output_topic instance."""
        assert agent_output_topic.name == AGENT_OUTPUT_TOPIC
        assert isinstance(agent_output_topic, OutputTopic)

    @pytest.mark.asyncio
    async def test_integration_add_generator_and_get_events(
        self, output_topic, sample_invoke_context
    ):
        """Integration test: add generator and consume events."""

        async def test_generator():
            yield [Message(content="Hello", role="assistant")]
            yield [Message(content=" World", role="assistant")]

        # Add generator
        output_topic.add_generator(
            generator=test_generator(),
            data=[],
            invoke_context=sample_invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
        )

        # Collect events
        events = []
        async for event in output_topic.get_events():
            events.append(event)
            if len(events) >= 2:  # We expect 2 events from the generator
                break

        assert len(events) == 2
        assert all(isinstance(event, OutputAsyncEvent) for event in events)

        # Wait for completion
        await output_topic.wait_for_completion()
