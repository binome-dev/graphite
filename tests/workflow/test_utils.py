from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.utils import consumption_of
from grafi.workflows.impl.utils import get_async_output_events


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

        # The aggregated event must be a NEW object: the source events (already
        # yielded/recorded) must not be mutated in place.
        assert result[0] is not event1
        assert event1.data[0].content == "Part1"
        assert event1.data[0].is_streaming is True
        assert event2.data[0].content == "Part2"

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


def _context() -> InvokeContext:
    return InvokeContext(
        conversation_id="test-conversation",
        invoke_id="test-invoke",
        assistant_request_id="test-request",
    )


class TestConsumptionOf:
    def test_records_the_consumer_taking_the_publication(self) -> None:
        publication = PublishToTopicEvent(
            name="topic1",
            type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
            publisher_name="producer",
            publisher_type="Node",
            invoke_context=_context(),
            offset=3,
            data=[Message(role="user", content="Test")],
        )

        consumed = consumption_of(publication, "test_node", "test_type")

        assert isinstance(consumed, ConsumeFromTopicEvent)
        assert (consumed.consumer_name, consumed.consumer_type) == (
            "test_node",
            "test_type",
        )
        assert (consumed.name, consumed.type, consumed.offset) == (
            "topic1",
            TopicType.AGENT_OUTPUT_TOPIC_TYPE,
            3,
        )
        assert consumed.invoke_context == publication.invoke_context
        assert consumed.data == publication.data
