from datetime import datetime
from unittest.mock import MagicMock

import pytest

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_base import TopicBase


class MockTopic(TopicBase):
    """A mock subclass to implement the required abstract methods."""

    def publish_data(
        self,
        invoke_context,
        publisher_name,
        publisher_type,
        data,
        consumed_event_ids,
    ):
        event = PublishToTopicEvent(
            event_id="event_2",
            name="topic1",
            offset=0,
            publisher_name=publisher_name,
            publisher_type=publisher_type,
            consumed_event_ids=consumed_event_ids,
            invoke_context=invoke_context,
            data=data,
            timestamp=datetime(2023, 1, 1, 13, 0),
        )

        # Add event to cache like the real implementation
        self.add_event(event)
        return event

    # can_consume and consume are now inherited from TopicBase


@pytest.fixture
def topic() -> TopicBase:
    """Fixture to create a mock topic instance."""
    topic = MockTopic(name="test_topic")
    topic.publish_event_handler = MagicMock()  # Mock the event handler
    return topic


def test_reset(topic: TopicBase, invoke_context: InvokeContext):
    """Ensure topic resets correctly."""
    message = Message(role="assistant", content="Test Message")

    topic.publish_data(invoke_context, "test_publisher", "test_type", [message], [])
    topic.reset()

    assert topic.event_cache.num_events() == 0  # All messages should be cleared
    # Consumption offsets are now managed internally by TopicEventCache


def test_restore_topic(topic: TopicBase, invoke_context: InvokeContext):
    """Ensure topic restores correctly from events."""
    event = PublishToTopicEvent(
        event_id="event_1",
        name="topic1",
        offset=0,
        publisher_name="publisher1",
        publisher_type="test",
        invoke_context=invoke_context,
        data=[Message(role="assistant", content="Test Message")],
        timestamp=datetime(2023, 1, 1, 13, 0),
    )

    topic.restore_topic(event)

    assert topic.event_cache.num_events() == 1
    # Event was restored to cache, verify by consuming it
    consumed_events = topic.consume("test_consumer")
    assert len(consumed_events) == 1
    assert consumed_events[0].event_id == "event_1"


def test_serialize_callable_function():
    """Test serialization of a regular function."""

    def custom_condition(messages):
        return len(messages) > 0

    topic = MockTopic(name="test_topic", condition=custom_condition)
    serialized = topic.serialize_callable()

    assert serialized["type"] == "function"
    assert serialized["name"] == "custom_condition"


def test_serialize_lambda():
    """Test serialization of a lambda function."""
    topic = MockTopic(name="test_topic", condition=lambda messages: len(messages) > 0)
    serialized = topic.serialize_callable()

    assert serialized["type"] == "lambda"
    assert "lambda messages:" in serialized["code"]  # Ensure lambda source is captured


def test_serialize_callable_object():
    """Test serialization of a callable object."""

    class CallableCondition:
        def __call__(self, messages):
            return len(messages) > 0

    condition_instance = CallableCondition()
    topic = MockTopic(name="test_topic", condition=condition_instance)
    serialized = topic.serialize_callable()

    assert serialized["type"] == "callable_object"
    assert serialized["class_name"] == "CallableCondition"
