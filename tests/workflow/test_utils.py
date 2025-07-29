import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.topic_base import TopicBase
from grafi.nodes.node import Node
from grafi.workflows.impl.utils import AsyncNodeTracker
from grafi.workflows.impl.utils import MergeIdleQueue
from grafi.workflows.impl.utils import a_get_node_input
from grafi.workflows.impl.utils import a_publish_events
from grafi.workflows.impl.utils import get_async_output_events
from grafi.workflows.impl.utils import get_node_input
from grafi.workflows.impl.utils import output_listener
from grafi.workflows.impl.utils import publish_events


class TestGetAsyncOutputEvents:
    def test_empty_events(self):
        result = get_async_output_events([])
        assert result == []

    def test_non_streaming_events(self):
        invoke_context = InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )
        message = Message(role="assistant", content="Hello", is_streaming=False)

        event1 = PublishToTopicEvent(
            topic_name="topic1",
            publisher_name="node1",
            publisher_type="test_node",
            invoke_context=invoke_context,
            offset=0,
            data=[message],
            consumed_events=[],
        )

        event2 = PublishToTopicEvent(
            topic_name="topic2",
            publisher_name="node2",
            publisher_type="test_node",
            invoke_context=invoke_context,
            offset=1,
            data=[message],
            consumed_events=[],
        )

        result = get_async_output_events([event1, event2])
        assert len(result) == 2
        assert result[0] == event1
        assert result[1] == event2

    def test_streaming_events_aggregation(self):
        invoke_context = InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )

        streaming_msg1 = Message(role="assistant", content="Hello ", is_streaming=True)
        streaming_msg2 = Message(role="assistant", content="World", is_streaming=True)

        event1 = PublishToTopicEvent(
            topic_name="topic1",
            publisher_name="node1",
            publisher_type="test_node",
            invoke_context=invoke_context,
            offset=0,
            data=[streaming_msg1],
            consumed_events=[],
        )

        event2 = PublishToTopicEvent(
            topic_name="topic1",
            publisher_name="node1",
            publisher_type="test_node",
            invoke_context=invoke_context,
            offset=1,
            data=[streaming_msg2],
            consumed_events=[],
        )

        result = get_async_output_events([event1, event2])
        assert len(result) == 1
        assert result[0].data[0].content == "Hello World"
        assert result[0].data[0].is_streaming is False

    def test_mixed_streaming_and_non_streaming(self):
        invoke_context = InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )

        streaming_msg = Message(role="assistant", content="Stream", is_streaming=True)
        non_streaming_msg = Message(
            role="assistant", content="Regular", is_streaming=False
        )

        event1 = PublishToTopicEvent(
            topic_name="topic1",
            publisher_name="node1",
            publisher_type="test_node",
            invoke_context=invoke_context,
            offset=0,
            data=[streaming_msg],
            consumed_events=[],
        )

        event2 = PublishToTopicEvent(
            topic_name="topic1",
            publisher_name="node1",
            publisher_type="test_node",
            invoke_context=invoke_context,
            offset=1,
            data=[non_streaming_msg],
            consumed_events=[],
        )

        result = get_async_output_events([event1, event2])
        assert len(result) == 2
        # Non-streaming event should be preserved as-is
        assert any(
            e.data[0].content == "Regular" and not e.data[0].is_streaming
            for e in result
        )
        # Streaming event should be aggregated (single streaming event stays as is)
        assert any(
            e.data[0].content == "Stream" and not e.data[0].is_streaming for e in result
        )

    def test_consume_event_aggregation(self):
        invoke_context = InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )

        streaming_msg1 = Message(role="assistant", content="Part1", is_streaming=True)
        streaming_msg2 = Message(role="assistant", content="Part2", is_streaming=True)

        event1 = ConsumeFromTopicEvent(
            topic_name="topic1",
            consumer_name="consumer1",
            consumer_type="test_consumer",
            invoke_context=invoke_context,
            offset=0,
            data=[streaming_msg1],
        )

        event2 = ConsumeFromTopicEvent(
            topic_name="topic1",
            consumer_name="consumer1",
            consumer_type="test_consumer",
            invoke_context=invoke_context,
            offset=1,
            data=[streaming_msg2],
        )

        result = get_async_output_events([event1, event2])
        assert len(result) == 1
        assert isinstance(result[0], ConsumeFromTopicEvent)
        assert result[0].data[0].content == "Part1Part2"
        assert result[0].data[0].is_streaming is False

    def test_output_event_aggregation(self):
        invoke_context = InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )

        streaming_msg = Message(role="assistant", content="Output", is_streaming=True)

        event = OutputTopicEvent(
            topic_name="output",
            publisher_name="node1",
            publisher_type="test_node",
            invoke_context=invoke_context,
            offset=0,
            data=[streaming_msg],
            consumed_events=[],
        )

        result = get_async_output_events([event])
        assert len(result) == 1
        assert isinstance(result[0], OutputTopicEvent)
        assert result[0].data[0].content == "Output"
        assert result[0].data[0].is_streaming is False


class TestPublishEvents:
    def test_publish_events_sync(self):
        # Mock node and topics
        mock_topic1 = MagicMock(spec=TopicBase)
        mock_topic2 = MagicMock(spec=TopicBase)

        node = MagicMock(spec=Node)
        node.name = "test_node"
        node.type = "test_type"
        node.publish_to = [mock_topic1, mock_topic2]

        invoke_context = InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )
        result = [Message(role="assistant", content="Test result")]
        consumed_events = []

        # Mock publish_data to return events
        mock_event1 = PublishToTopicEvent(
            topic_name="topic1",
            publisher_name=node.name,
            publisher_type=node.type,
            invoke_context=invoke_context,
            offset=0,
            data=result,
            consumed_events=consumed_events,
        )
        mock_event2 = PublishToTopicEvent(
            topic_name="topic2",
            publisher_name=node.name,
            publisher_type=node.type,
            invoke_context=invoke_context,
            offset=1,
            data=result,
            consumed_events=consumed_events,
        )

        mock_topic1.publish_data.return_value = mock_event1
        mock_topic2.publish_data.return_value = mock_event2

        all_events = publish_events(node, invoke_context, result, consumed_events)

        # The function returns all_events which includes both consumed and published
        assert len(all_events) == 2  # 0 consumed + 2 published
        assert mock_event1 in all_events
        assert mock_event2 in all_events

        # Verify topics were called correctly
        mock_topic1.publish_data.assert_called_once_with(
            invoke_context=invoke_context,
            publisher_name=node.name,
            publisher_type=node.type,
            data=result,
            consumed_events=consumed_events,
        )

    @pytest.mark.asyncio
    async def test_a_publish_events(self):
        # Mock node and topics
        mock_topic1 = AsyncMock(spec=TopicBase)
        mock_topic2 = AsyncMock(spec=TopicBase)

        node = MagicMock(spec=Node)
        node.name = "test_node"
        node.type = "test_type"
        node.publish_to = [mock_topic1, mock_topic2]

        invoke_context = InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )
        result = [Message(role="assistant", content="Test result")]
        consumed_events = []

        # Mock a_publish_data to return events
        mock_event1 = PublishToTopicEvent(
            topic_name="topic1",
            publisher_name=node.name,
            publisher_type=node.type,
            invoke_context=invoke_context,
            offset=0,
            data=result,
            consumed_events=consumed_events,
        )
        mock_event2 = None  # Test case where topic doesn't publish

        mock_topic1.a_publish_data.return_value = mock_event1
        mock_topic2.a_publish_data.return_value = mock_event2

        published_events = await a_publish_events(
            node, result, invoke_context, consumed_events
        )

        assert len(published_events) == 1
        assert published_events[0] == mock_event1

        # Verify topics were called correctly
        mock_topic1.a_publish_data.assert_called_once_with(
            data=result,
            invoke_context=invoke_context,
            publisher_name=node.name,
            publisher_type=node.type,
            consumed_events=consumed_events,
        )


class TestGetNodeInput:
    def test_get_node_input_sync(self):
        # Mock node and subscribed topics
        mock_topic1 = MagicMock(spec=TopicBase)
        mock_topic2 = MagicMock(spec=TopicBase)

        node = MagicMock(spec=Node)
        node.name = "test_node"
        node.type = "test_type"
        node._subscribed_topics = {"topic1": mock_topic1, "topic2": mock_topic2}

        invoke_context = InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )

        # Mock can_consume and consume methods
        mock_topic1.can_consume.return_value = True
        mock_topic2.can_consume.return_value = False  # This topic has no messages

        mock_event = MagicMock()
        mock_event.invoke_context = invoke_context
        mock_event.topic_name = "topic1"
        mock_event.offset = 0
        mock_event.data = [Message(role="user", content="Test")]

        mock_topic1.consume.return_value = [mock_event]

        consumed_events = get_node_input(node)

        assert len(consumed_events) == 1
        assert isinstance(consumed_events[0], ConsumeFromTopicEvent)
        assert consumed_events[0].consumer_name == node.name
        assert consumed_events[0].consumer_type == node.type
        assert consumed_events[0].topic_name == "topic1"

        # Verify can_consume was called
        mock_topic1.can_consume.assert_called_once_with(node.name)
        mock_topic2.can_consume.assert_called_once_with(node.name)

        # Verify consume was only called on topic1
        mock_topic1.consume.assert_called_once_with(node.name)
        mock_topic2.consume.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_get_node_input(self):
        # Mock node and subscribed topics
        mock_topic1 = AsyncMock(spec=TopicBase)
        mock_topic2 = AsyncMock(spec=TopicBase)

        node = MagicMock(spec=Node)
        node.name = "test_node"
        node.type = "test_type"
        node._subscribed_topics = {"topic1": mock_topic1, "topic2": mock_topic2}

        invoke_context = InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )

        # Mock can_consume and a_consume methods
        mock_topic1.can_consume.return_value = True
        mock_topic2.can_consume.return_value = True

        # Create different types of events
        publish_event = PublishToTopicEvent(
            topic_name="topic1",
            publisher_name="publisher",
            publisher_type="test",
            invoke_context=invoke_context,
            offset=0,
            data=[Message(role="user", content="Published")],
            consumed_events=[],
        )

        output_event = OutputTopicEvent(
            topic_name="topic2",
            publisher_name="publisher",
            publisher_type="test",
            invoke_context=invoke_context,
            offset=1,
            data=[Message(role="assistant", content="Output")],
            consumed_events=[],
        )

        mock_topic1.a_consume.return_value = [publish_event]
        mock_topic2.a_consume.return_value = [output_event]

        consumed_events, ignored_events = await a_get_node_input(node)

        assert len(consumed_events) == 1
        assert len(ignored_events) == 1

        # Verify PublishToTopicEvent was converted to ConsumeFromTopicEvent
        assert isinstance(consumed_events[0], ConsumeFromTopicEvent)
        assert consumed_events[0].consumer_name == node.name
        assert consumed_events[0].data[0].content == "Published"

        # Verify OutputTopicEvent was ignored
        assert isinstance(ignored_events[0], ConsumeFromTopicEvent)
        assert ignored_events[0].data[0].content == "Output"


class TestAsyncNodeTracker:
    @pytest.mark.asyncio
    async def test_enter_leave_idle(self):
        tracker = AsyncNodeTracker()

        assert tracker.is_idle()

        await tracker.enter("node1")
        assert not tracker.is_idle()

        await tracker.enter("node2")
        assert not tracker.is_idle()

        await tracker.leave("node1")
        assert not tracker.is_idle()

        await tracker.leave("node2")
        assert tracker.is_idle()

    @pytest.mark.asyncio
    async def test_wait_idle_event(self):
        tracker = AsyncNodeTracker()

        # Initially idle
        assert tracker.is_idle()

        # Enter a node
        await tracker.enter("node1")

        # Create task to wait for idle
        idle_task = asyncio.create_task(tracker.wait_idle_event())

        # Give some time to ensure wait started
        await asyncio.sleep(0.01)

        # Task should not be done yet
        assert not idle_task.done()

        # Leave node to trigger idle
        await tracker.leave("node1")

        # Wait should complete
        await asyncio.wait_for(idle_task, timeout=1.0)

    @pytest.mark.asyncio
    async def test_reset(self):
        tracker = AsyncNodeTracker()

        await tracker.enter("node1")
        assert not tracker.is_idle()

        tracker.reset()
        assert tracker.is_idle()
        assert len(tracker._active) == 0


class TestOutputListener:
    @pytest.mark.asyncio
    async def test_output_listener_with_messages(self):
        # Mock topic and tracker
        mock_topic = AsyncMock(spec=TopicBase)
        tracker = AsyncNodeTracker()
        queue = asyncio.Queue()
        consumer_name = "test_consumer"

        # Mock events
        event1 = MagicMock()
        event2 = MagicMock()

        # Setup mock behavior
        call_count = 0

        async def mock_consume(name):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [event1]
            elif call_count == 2:
                return [event2]
            else:
                return []

        mock_topic.a_consume = mock_consume
        mock_topic.can_consume.side_effect = lambda name: call_count < 3

        # Run output listener in background
        listener_task = asyncio.create_task(
            output_listener(mock_topic, queue, consumer_name, tracker)
        )

        # Give listener time to process
        await asyncio.sleep(0.1)

        # Check queue contents
        assert queue.qsize() == 2
        assert await queue.get() == event1
        assert await queue.get() == event2

        # Cancel listener
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_output_listener_exits_on_idle_and_empty(self):
        # Mock topic and tracker
        mock_topic = AsyncMock(spec=TopicBase)
        tracker = AsyncNodeTracker()
        queue = asyncio.Queue()
        consumer_name = "test_consumer"

        # No messages available
        mock_topic.a_consume.return_value = []
        mock_topic.can_consume.return_value = False

        # Tracker is idle
        assert tracker.is_idle()

        # Run output listener
        await output_listener(mock_topic, queue, consumer_name, tracker)

        # Should have exited cleanly
        assert queue.empty()


class TestMergeIdleQueue:
    @pytest.mark.asyncio
    async def test_merge_idle_queue_iteration(self):
        queue = asyncio.Queue()
        tracker = AsyncNodeTracker()

        # Add items to queue
        await queue.put("item1")
        await queue.put("item2")

        merge_queue = MergeIdleQueue(queue, tracker)

        # Get items
        items = []
        async for item in merge_queue:
            items.append(item)
            if len(items) == 2:
                break

        assert items == ["item1", "item2"]

    @pytest.mark.asyncio
    async def test_merge_idle_queue_stops_on_idle_and_empty(self):
        queue = asyncio.Queue()
        tracker = AsyncNodeTracker()

        # Queue is empty and tracker is idle
        assert queue.empty()
        assert tracker.is_idle()

        merge_queue = MergeIdleQueue(queue, tracker)

        items = []
        async for item in merge_queue:
            items.append(item)

        # Should have stopped iteration
        assert items == []

    @pytest.mark.asyncio
    async def test_merge_idle_queue_waits_for_items(self):
        queue = asyncio.Queue()
        tracker = AsyncNodeTracker()

        # Enter a node to prevent idle
        await tracker.enter("node1")

        merge_queue = MergeIdleQueue(queue, tracker)

        async def add_item_later():
            await asyncio.sleep(0.1)
            await queue.put("delayed_item")
            await tracker.leave("node1")

        # Start adding item in background
        asyncio.create_task(add_item_later())

        # Get items
        items = []
        async for item in merge_queue:
            items.append(item)
            if len(items) == 1:
                break

        assert items == ["delayed_item"]
