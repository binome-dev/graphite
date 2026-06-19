from datetime import datetime

import pytest

from grafi.common.callable_ref import CallableSerializationError
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_base import always_true
from grafi.topics.topic_base import deserialize_condition


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


# Module-level condition used to exercise reference-based serialization.
def module_level_condition(event: PublishToTopicEvent) -> bool:
    """A named, importable condition -> serializes as an import reference."""
    return True


def test_default_condition_serializes_as_reference():
    """The default condition is a named function, not an inline lambda, so it
    serializes as a tiny import reference rather than inline code."""
    topic = MockTopic(name="default_condition_topic")
    data = topic.to_dict()
    assert data["condition"] == {"ref": f"{always_true.__module__}:always_true"}


def test_named_condition_roundtrips_via_reference():
    topic = MockTopic(name="named_topic", condition=module_level_condition)
    data = topic.to_dict()
    assert data["condition"] == {
        "ref": f"{module_level_condition.__module__}:module_level_condition"
    }
    assert deserialize_condition(data) is module_level_condition


def test_lambda_condition_cannot_be_serialized():
    # A lambda is neither an importable reference nor a component, so it cannot
    # be serialized without pickle -- use a named predicate or a component.
    topic = MockTopic(name="lambda_topic", condition=lambda _: False)
    with pytest.raises(CallableSerializationError, match="without pickle"):
        topic.to_dict()


def test_missing_condition_defaults_to_always_true():
    """A manifest without a condition restores to the always-publish default."""
    assert deserialize_condition({"name": "no_condition"}) is always_true


def test_legacy_pickle_condition_dict_is_rejected():
    """Legacy {"base64": ...} pickle conditions are no longer supported."""
    with pytest.raises(CallableSerializationError, match="pickle payload"):
        deserialize_condition(
            {"name": "legacy", "condition": {"base64": "x", "code": "lambda _: True"}}
        )
