import pytest

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_base import TopicType
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.topic import Topic


@pytest.fixture
def topic() -> InputTopic:
    """Fixture to create a Topic instance with a mocked publish event handler."""
    topic = InputTopic(name="agent_input_topic")
    return topic


@pytest.fixture
def invoke_context() -> InvokeContext:
    """Fixture providing a mock InvokeContext."""
    return InvokeContext(
        conversation_id="test_conversation",
        invoke_id="test_invoke",
        assistant_request_id="test_request",
    )


@pytest.mark.asyncio
async def test_publish_message(topic: Topic, invoke_context: InvokeContext):
    """Test publishing a message to the topic."""
    message = Message(role="assistant", content="Test Message")

    event = await topic.a_publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            name="agent_input_topic",
            type=TopicType.AGENT_INPUT_TOPIC_TYPE,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message],
        )
    )

    assert topic.name == "agent_input_topic"
    assert topic.type == TopicType.AGENT_INPUT_TOPIC_TYPE
    # Note: direct access to internal queue structure may vary based on implementation
    assert event.publisher_name == "test_publisher"
    assert event.publisher_type == "test_type"
    assert event.offset == 0


@pytest.mark.asyncio
async def test_can_consume(topic: Topic, invoke_context: InvokeContext):
    """Test checking if a consumer can consume messages."""
    message = Message(role="assistant", content="Test Message")

    # Before publishing, consumer should not be able to consume
    assert not await topic.a_can_consume("consumer_1")

    # Publish a message
    await topic.a_publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            name="agent_input_topic",
            type=TopicType.AGENT_INPUT_TOPIC_TYPE,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message],
        )
    )

    # Now the consumer should be able to consume
    assert await topic.a_can_consume("consumer_1")


@pytest.mark.asyncio
async def test_consume_messages(topic: Topic, invoke_context: InvokeContext):
    """Test consuming messages from the topic."""
    message1 = Message(role="assistant", content="Message 1")
    message2 = Message(role="assistant", content="Message 2")

    await topic.a_publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            name="agent_input_topic",
            type=TopicType.AGENT_INPUT_TOPIC_TYPE,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message1],
        )
    )
    await topic.a_publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            name="agent_input_topic",
            type=TopicType.AGENT_INPUT_TOPIC_TYPE,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message2],
        )
    )

    consumed_messages = await topic.a_consume("consumer_1")

    assert len(consumed_messages) == 2  # Consumer should receive both messages
    assert consumed_messages[0].offset == 0
    assert consumed_messages[1].offset == 1
    # Note: offset tracking is handled internally by the event queue


@pytest.mark.asyncio
async def test_consume_no_new_messages(topic: Topic, invoke_context: InvokeContext):
    """Ensure no messages are consumed when there are no new ones."""
    message = Message(role="assistant", content="Test Message")

    await topic.a_publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            name="agent_input_topic",
            type=TopicType.AGENT_INPUT_TOPIC_TYPE,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message],
        )
    )

    # First consume
    await topic.a_consume("consumer_1")
    # Second consume (should return empty list)
    consumed_messages = await topic.a_consume("consumer_1")

    assert len(consumed_messages) == 0  # Should return an empty list


@pytest.mark.asyncio
async def test_offset_updates_correctly(topic: Topic, invoke_context: InvokeContext):
    """Ensure the offset updates correctly for multiple consumers."""
    message1 = Message(role="assistant", content="Message 1")
    message2 = Message(role="assistant", content="Message 2")

    await topic.a_publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            name="agent_input_topic",
            type=TopicType.AGENT_INPUT_TOPIC_TYPE,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message1],
        )
    )
    await topic.a_publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            name="agent_input_topic",
            type=TopicType.AGENT_INPUT_TOPIC_TYPE,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message2],
        )
    )

    # Consumer 1 consumes both messages
    consumed_messages_1 = await topic.a_consume("consumer_1")
    assert len(consumed_messages_1) == 2

    # Consumer 1 has no more messages to consume
    assert not await topic.a_can_consume("consumer_1")
    consumed_messages_1_again = await topic.a_consume("consumer_1")
    assert len(consumed_messages_1_again) == 0

    # Consumer 2 starts fresh and should receive both messages
    consumed_messages_2 = await topic.a_consume("consumer_2")
    assert len(consumed_messages_2) == 2

    # Consumer 2 has no more messages to consume
    assert not await topic.a_can_consume("consumer_2")
