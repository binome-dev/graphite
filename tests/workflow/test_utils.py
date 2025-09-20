from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.utils import get_async_output_events
from grafi.workflows.impl.utils import get_node_input
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
            name="topic1",
            publisher_name="node1",
            publisher_type="test_node",
            invoke_context=invoke_context,
            offset=0,
            data=[message],
            consumed_events=[],
        )

        event2 = PublishToTopicEvent(
            name="topic2",
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
            name="topic1",
            publisher_name="node1",
            publisher_type="test_node",
            invoke_context=invoke_context,
            offset=0,
            data=[streaming_msg1],
            consumed_events=[],
        )

        event2 = PublishToTopicEvent(
            name="topic1",
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
            name="topic1",
            publisher_name="node1",
            publisher_type="test_node",
            invoke_context=invoke_context,
            offset=0,
            data=[streaming_msg],
            consumed_events=[],
        )

        event2 = PublishToTopicEvent(
            name="topic1",
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
            name="topic1",
            consumer_name="consumer1",
            consumer_type="test_consumer",
            invoke_context=invoke_context,
            offset=0,
            data=[streaming_msg1],
        )

        event2 = ConsumeFromTopicEvent(
            name="topic1",
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

        event = PublishToTopicEvent(
            name="output",
            publisher_name="node1",
            publisher_type="test_node",
            invoke_context=invoke_context,
            offset=0,
            data=[streaming_msg],
            consumed_events=[],
        )

        result = get_async_output_events([event])
        assert len(result) == 1
        assert isinstance(result[0], PublishToTopicEvent)
        assert result[0].data[0].content == "Output"
        assert result[0].data[0].is_streaming is False


class TestPublishEvents:
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

        # Mock publish_data to return events
        mock_event1 = PublishToTopicEvent(
            name="topic1",
            publisher_name=node.name,
            publisher_type=node.type,
            invoke_context=invoke_context,
            offset=0,
            data=result,
            consumed_events=consumed_events,
        )
        mock_event2 = None  # Test case where topic doesn't publish

        mock_topic1.publish_data.return_value = mock_event1
        mock_topic2.publish_data.return_value = mock_event2

        publish_to_event = PublishToTopicEvent(
            invoke_context=invoke_context,
            publisher_name=node.name,
            publisher_type=node.type,
            data=result,
            consumed_event_ids=[event.event_id for event in consumed_events],
        )

        published_events = await publish_events(node, publish_to_event)

        assert len(published_events) == 1
        assert published_events[0] == mock_event1

        # Verify topics were called correctly
        mock_topic1.publish_data.assert_called_once_with(publish_to_event)


class TestGetNodeInput:
    @pytest.mark.asyncio
    async def test_get_node_input_async(self):
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
        mock_event.name = "topic1"
        mock_event.type = TopicType.AGENT_OUTPUT_TOPIC_TYPE
        mock_event.offset = 0
        mock_event.data = [Message(role="user", content="Test")]

        mock_topic1.consume.return_value = [mock_event]

        consumed_events = await get_node_input(node)

        assert len(consumed_events) == 1
        assert isinstance(consumed_events[0], ConsumeFromTopicEvent)
        assert consumed_events[0].consumer_name == node.name
        assert consumed_events[0].consumer_type == node.type
        assert consumed_events[0].name == "topic1"

        # Verify can_consume was called
        mock_topic1.can_consume.assert_called_once_with(node.name)
        mock_topic2.can_consume.assert_called_once_with(node.name)

        # Verify consume was only called on topic1
        mock_topic1.consume.assert_called_once_with(node.name)
        mock_topic2.consume.assert_not_called()
