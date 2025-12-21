from datetime import datetime

import pytest

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_base import serialize_condition


class MockTopic(TopicBase):
    """A mock subclass to implement the required abstract methods."""

    pass

    # can_consume and consume are now inherited from TopicBase


@pytest.fixture
def topic() -> TopicBase:
    """Fixture to create a mock topic instance."""
    topic = MockTopic(name="test_topic")
    return topic


@pytest.mark.asyncio
async def test_reset(topic: TopicBase, invoke_context: InvokeContext):
    """Ensure topic resets correctly."""
    message = Message(role="assistant", content="Test Message")

    publish_to_topic_event = PublishToTopicEvent(
        event_id="event_2",
        name="test_topic",
        offset=0,
        publisher_name="test_publisher",
        publisher_type="test_type",
        consumed_event_ids=[],
        invoke_context=invoke_context,
        data=[message],
        timestamp=datetime(2023, 1, 1, 13, 0),
    )

    await topic.publish_data(publish_to_topic_event)
    await topic.reset()

    assert await topic.consume("dummy", 1) == []  # All messages should be cleared
    # Consumption offsets are now managed internally by TopicEventQueue


@pytest.mark.asyncio
async def test_restore_topic(topic: TopicBase, invoke_context: InvokeContext):
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

    await topic.restore_topic(event)

    # Event was restored to cache, verify by consuming it
    consumed_events = await topic.consume("test_consumer")
    assert len(consumed_events) == 1
    assert consumed_events[0].event_id == "event_1"


# Module-level definitions for serialize_condition tests
def module_level_function(x):
    """A regular function defined at module level."""
    return x > 0


def test_serialize_condition_def_function():
    """Test serialization of a regular function defined with def."""
    result = serialize_condition(module_level_function)
    assert "def module_level_function(x):" in result
    assert "return x > 0" in result


def test_serialize_condition_lambda_literal():
    """Test serialization of a lambda defined at module level."""
    condition = lambda x: x < 10  # noqa: E731
    result = serialize_condition(condition)
    assert "lambda" in result
    assert result.startswith("lambda")


def test_serialize_condition_lambda_in_assignment():
    """Test serialization of lambda from assignment statement."""
    # This simulates Case B: assignment to lambda
    result = serialize_condition(lambda x: x < 10)
    assert "lambda" in result


def test_serialize_condition_inline_lambda():
    """Test serialization of an inline lambda expression."""
    result = serialize_condition(lambda y: y * 2)
    assert "lambda" in result


def test_serialize_condition_error_on_builtin():
    """Test that built-in functions raise ValueError."""
    with pytest.raises(ValueError, match="Cannot serialize callable"):
        serialize_condition(len)


def test_serialize_condition_error_on_dynamic():
    """Test that dynamically created callables raise ValueError."""
    # Create a callable that inspect.getsource can't handle
    dynamic_fn = eval("lambda x: x + 1")
    with pytest.raises(ValueError, match="Cannot serialize callable"):
        serialize_condition(dynamic_fn)
