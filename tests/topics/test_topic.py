from unittest.mock import MagicMock

import pytest

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic import Topic


@pytest.fixture
def topic() -> Topic:
    """Fixture to create a Topic instance with a mocked publish event handler."""
    topic = Topic(name="test_topic")
    topic.publish_event_handler = MagicMock()  # Mock the event handler
    return topic


def test_publish_message(topic: Topic, invoke_context: InvokeContext):
    """Test publishing a message to the topic."""
    message = Message(role="assistant", content="Test Message")

    event = topic.publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message],
            consumed_event_ids=[],
        )
    )

    assert topic.event_cache.num_events() == 1  # Ensure the message was published
    # The event_cache doesn't have a get() method, it manages events internally
    assert topic.publish_event_handler.called  # Ensure the publish handler was invoked
    assert event.publisher_name == "test_publisher"
    assert event.publisher_type == "test_type"
    assert event.offset == 0


def test_can_consume(topic: Topic, invoke_context: InvokeContext):
    """Test checking if a consumer can consume messages."""
    message = Message(role="assistant", content="Test Message")

    # Before publishing, consumer should not be able to consume
    assert not topic.can_consume("consumer_1")

    # Publish a message
    topic.publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message],
            consumed_event_ids=[],
        )
    )

    # Now the consumer should be able to consume
    assert topic.can_consume("consumer_1")


def test_consume_messages(topic: Topic, invoke_context: InvokeContext):
    """Test consuming messages from the topic."""
    message1 = Message(role="assistant", content="Message 1")
    message2 = Message(role="assistant", content="Message 2")

    topic.publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message1],
            consumed_event_ids=[],
        )
    )
    topic.publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message2],
            consumed_event_ids=[],
        )
    )

    consumed_messages = topic.consume("consumer_1")

    assert len(consumed_messages) == 2  # Consumer should receive both messages
    assert consumed_messages[0].offset == 0
    assert consumed_messages[1].offset == 1
    # Consumption offsets are now managed internally by TopicEventCache
    # Test that consumer can't consume again (has consumed all available messages)
    assert not topic.can_consume("consumer_1")


def test_consume_no_new_messages(topic: Topic, invoke_context: InvokeContext):
    """Ensure no messages are consumed when there are no new ones."""
    message = Message(role="assistant", content="Test Message")

    topic.publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message],
            consumed_event_ids=[],
        )
    )

    # First consume
    topic.consume("consumer_1")
    # Second consume (should return empty list)
    consumed_messages = topic.consume("consumer_1")

    assert len(consumed_messages) == 0  # Should return an empty list


def test_offset_updates_correctly(topic: Topic, invoke_context: InvokeContext):
    """Ensure the offset updates correctly for multiple consumers."""
    message1 = Message(role="assistant", content="Message 1")
    message2 = Message(role="assistant", content="Message 2")

    topic.publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message1],
            consumed_event_ids=[],
        )
    )
    topic.publish_data(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=[message2],
            consumed_event_ids=[],
        )
    )

    # Consumer 1 consumes both messages
    consumed_messages_1 = topic.consume("consumer_1")
    assert len(consumed_messages_1) == 2

    # Consumer 1 has no more messages to consume
    assert not topic.can_consume("consumer_1")
    consumed_messages_1_again = topic.consume("consumer_1")
    assert len(consumed_messages_1_again) == 0

    # Consumer 2 starts fresh and should receive both messages
    consumed_messages_2 = topic.consume("consumer_2")
    assert len(consumed_messages_2) == 2

    # Consumer 2 has no more messages to consume
    assert not topic.can_consume("consumer_2")


# Ensure a topic can be created
