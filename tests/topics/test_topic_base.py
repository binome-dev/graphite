from datetime import datetime

import pytest

from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_base import TopicBase


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


@pytest.mark.asyncio
async def test_restore_topic_consume_event_does_not_skip_next(
    topic: TopicBase, invoke_context: InvokeContext
):
    """Restoring a ConsumeFromTopicEvent advances the consumer's cursor to the
    recorded commit point only, leaving the immediately following offset
    available. Regression for the recovery off-by-one that skipped one event."""
    for i in range(3):
        await topic.restore_topic(
            PublishToTopicEvent(
                event_id=f"event_{i}",
                name="test_topic",
                offset=i,
                publisher_name="publisher1",
                publisher_type="test",
                invoke_context=invoke_context,
                data=[Message(role="assistant", content=f"m{i}")],
                timestamp=datetime(2023, 1, 1, 13, 0),
            )
        )

    # The consumer had committed through offset 0 before the crash.
    await topic.restore_topic(
        ConsumeFromTopicEvent(
            event_id="consume_0",
            name="test_topic",
            offset=0,
            consumer_name="c",
            consumer_type="Node",
            invoke_context=invoke_context,
            data=[Message(role="assistant", content="m0")],
        )
    )

    # Offsets 1 and 2 remain available (offset 1 is NOT skipped).
    remaining = await topic.consume("c")
    assert [event.offset for event in remaining] == [1, 2]


def test_to_dict_has_no_condition():
    """Topics are pure queues -- the manifest carries only name and type."""
    topic = MockTopic(name="plain_topic")
    assert topic.to_dict() == {"name": "plain_topic", "type": topic.type.value}


@pytest.mark.asyncio
async def test_publish_data_always_enqueues(
    topic: TopicBase, invoke_context: InvokeContext
):
    """publish_data stamps name/type and enqueues -- routing lives on the node."""
    event = PublishToTopicEvent(
        publisher_name="p",
        publisher_type="t",
        invoke_context=invoke_context,
        consumed_event_ids=[],
        data=[Message(role="assistant", content="hi")],
    )
    published = await topic.publish_data(event)
    assert published is not None
    assert published.name == "test_topic"

    consumed = await topic.consume("c")
    assert len(consumed) == 1


@pytest.mark.asyncio
async def test_destination_publications_have_distinct_ids_and_source_lineage(
    invoke_context: InvokeContext,
) -> None:
    a, b = MockTopic(name="a"), MockTopic(name="b")
    source = PublishToTopicEvent(
        name="source",
        offset=-1,
        invoke_context=invoke_context,
        data=[Message(role="assistant", content="hello")],
    )
    snapshot = source.model_dump()
    first = await a.publish_data(source)
    second = await b.publish_data(source)
    repeated = await a.publish_data(source)
    assert (
        len({source.event_id, first.event_id, second.event_id, repeated.event_id}) == 4
    )
    assert (
        first.emission_id
        == second.emission_id
        == repeated.emission_id
        == source.event_id
    )
    assert [first.offset, second.offset, repeated.offset] == [0, 0, 1]
    assert source.model_dump() == snapshot
    first.data[0].content = "changed"
    assert source.data[0].content == second.data[0].content == "hello"

    store = EventStoreInMemory()
    await store.record_events([first, second, repeated, first])
    assert await store.get_events() == [first, second, repeated]
    restored = MockTopic(name="a")
    await restored.restore_topic(first)
    replayed = await restored.consume("consumer", timeout=0)
    assert replayed[0].event_id == first.event_id
    assert replayed[0].emission_id == source.event_id
    # Republishing uses the immediate source publication, not its ancestor.
    forwarded = await b.publish_data(first)
    assert forwarded.emission_id == first.event_id
    assert forwarded.event_id not in {source.event_id, first.event_id, second.event_id}
