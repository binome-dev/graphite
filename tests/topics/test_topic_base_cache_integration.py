import asyncio
from datetime import datetime

import pytest

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.output_topic import OutputTopic
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic_event_cache import TopicEventCache


class TestTopicBaseCacheIntegration:
    @pytest.fixture
    def invoke_context(self):
        return InvokeContext(
            conversation_id="test-conversation",
            invoke_id="test-invoke",
            assistant_request_id="test-request",
        )

    @pytest.fixture
    def sample_messages(self):
        return [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
        ]

    @pytest.fixture
    def topic(self):
        return Topic(name="test_topic")

    @pytest.fixture
    def output_topic(self):
        return OutputTopic(name="output_topic")

    def test_topic_initialization_with_cache(self):
        topic = Topic(name="test")
        assert topic.name == "test"
        assert isinstance(topic.event_cache, TopicEventCache)
        assert topic.event_cache.name == ""  # Default cache name is empty string
        assert topic.event_cache.num_events() == 0

    def test_publish_and_consume_single_event(
        self, topic, invoke_context, sample_messages
    ):
        # Publish an event
        event = topic.publish_data(
            invoke_context=invoke_context,
            publisher_name="publisher1",
            publisher_type="test_publisher",
            data=sample_messages,
            consumed_events=[],
        )

        assert event is not None
        assert event.topic_name == "test_topic"
        assert event.data == sample_messages
        assert topic.event_cache.num_events() == 1

        # Consume the event
        assert topic.can_consume("consumer1")
        consumed_events = topic.consume("consumer1")
        assert len(consumed_events) == 1
        assert consumed_events[0] == event

        # Cannot consume again
        assert not topic.can_consume("consumer1")

    def test_multiple_consumers(self, topic, invoke_context, sample_messages):
        # Publish an event
        event = topic.publish_data(
            invoke_context=invoke_context,
            publisher_name="publisher1",
            publisher_type="test_publisher",
            data=sample_messages,
            consumed_events=[],
        )

        # Multiple consumers can consume the same event
        consumed1 = topic.consume("consumer1")
        consumed2 = topic.consume("consumer2")

        assert len(consumed1) == 1
        assert len(consumed2) == 1
        assert consumed1[0] == event
        assert consumed2[0] == event

        # Each consumer maintains its own offset
        assert not topic.can_consume("consumer1")
        assert not topic.can_consume("consumer2")

    def test_conditional_publishing(self, invoke_context):
        # Create topic with condition
        topic = Topic(
            name="conditional_topic",
            condition=lambda messages: any(m.role == "user" for m in messages),
        )

        # Message that meets condition
        user_messages = [Message(role="user", content="Hello")]
        event1 = topic.publish_data(
            invoke_context=invoke_context,
            publisher_name="publisher1",
            publisher_type="test_publisher",
            data=user_messages,
            consumed_events=[],
        )
        assert event1 is not None

        # Message that doesn't meet condition
        assistant_messages = [Message(role="assistant", content="Hi")]
        event2 = topic.publish_data(
            invoke_context=invoke_context,
            publisher_name="publisher1",
            publisher_type="test_publisher",
            data=assistant_messages,
            consumed_events=[],
        )
        assert event2 is None

        # Only one event should be in cache
        assert topic.event_cache.num_events() == 1

    def test_reset_functionality(self, topic, invoke_context, sample_messages):
        # Publish some events
        for i in range(3):
            topic.publish_data(
                invoke_context=invoke_context,
                publisher_name=f"publisher{i}",
                publisher_type="test_publisher",
                data=sample_messages,
                consumed_events=[],
            )

        # Consume some events
        topic.consume("consumer1")
        assert topic.event_cache._consumed["consumer1"] > 0

        # Reset the topic
        topic.reset()

        # Verify everything is cleared
        assert topic.event_cache.num_events() == 0
        assert not topic.can_consume("consumer1")

    @pytest.mark.asyncio
    async def test_async_publish_and_consume(
        self, topic, invoke_context, sample_messages
    ):
        # Async publish
        event = await topic.a_publish_data(
            invoke_context=invoke_context,
            publisher_name="async_publisher",
            publisher_type="test_publisher",
            data=sample_messages,
            consumed_events=[],
        )

        assert event is not None
        assert topic.event_cache.num_events() == 1

        # Async consume
        consumed_events = await topic.a_consume("async_consumer")
        assert len(consumed_events) == 1
        assert consumed_events[0] == event

    @pytest.mark.asyncio
    async def test_async_consume_with_wait(
        self, topic, invoke_context, sample_messages
    ):
        # Start consumer waiting for events
        consume_task = asyncio.create_task(
            topic.a_consume("waiting_consumer", timeout=1.0)
        )

        # Give it time to start waiting
        await asyncio.sleep(0.1)

        # Publish an event
        event = await topic.a_publish_data(
            invoke_context=invoke_context,
            publisher_name="publisher",
            publisher_type="test_publisher",
            data=sample_messages,
            consumed_events=[],
        )

        # Consumer should receive the event
        consumed_events = await consume_task
        assert len(consumed_events) == 1
        assert consumed_events[0] == event

    def test_restore_topic_from_publish_event(
        self, topic, invoke_context, sample_messages
    ):
        # Create a publish event
        event = PublishToTopicEvent(
            event_id="restore-event-1",
            topic_name="test_topic",
            offset=0,
            publisher_name="restore_publisher",
            publisher_type="test_publisher",
            consumed_event_ids=[],
            invoke_context=invoke_context,
            data=sample_messages,
            timestamp=datetime.now(),
        )

        # Restore the topic
        topic.restore_topic(event)

        # Verify event was added to cache
        assert topic.event_cache.num_events() == 1
        consumed = topic.consume("consumer1")
        assert len(consumed) == 1
        assert consumed[0] == event

    def test_restore_topic_from_consume_event(
        self, topic, invoke_context, sample_messages
    ):
        # First, publish an event
        publish_event = topic.publish_data(
            invoke_context=invoke_context,
            publisher_name="publisher",
            publisher_type="test_publisher",
            data=sample_messages,
            consumed_events=[],
        )

        # Create a consume event
        consume_event = ConsumeFromTopicEvent(
            event_id="consume-event-1",
            topic_name="test_topic",
            consumer_name="consumer1",
            consumer_type="test_consumer",
            offset=0,
            data=sample_messages,
            invoke_context=invoke_context,
            timestamp=datetime.now(),
        )

        # Restore from consume event
        topic.restore_topic(consume_event)

        # Verify consumer offset was updated
        assert not topic.can_consume("consumer1")  # Already consumed
        assert topic.event_cache._consumed["consumer1"] == 1
        assert topic.event_cache._committed["consumer1"] == 0

    @pytest.mark.asyncio
    async def test_async_restore_topic(self, topic, invoke_context, sample_messages):
        # Create events
        publish_event = PublishToTopicEvent(
            event_id="async-restore-1",
            topic_name="test_topic",
            offset=0,
            publisher_name="restore_publisher",
            publisher_type="test_publisher",
            consumed_event_ids=[],
            invoke_context=invoke_context,
            data=sample_messages,
            timestamp=datetime.now(),
        )

        consume_event = ConsumeFromTopicEvent(
            event_id="async-consume-1",
            topic_name="test_topic",
            consumer_name="consumer1",
            consumer_type="test_consumer",
            offset=0,
            data=sample_messages,
            invoke_context=invoke_context,
            timestamp=datetime.now(),
        )

        # Restore asynchronously
        await topic.a_restore_topic(publish_event)
        await topic.a_restore_topic(consume_event)

        # Verify restoration
        assert topic.event_cache.num_events() == 1
        assert not topic.can_consume("consumer1")

    @pytest.mark.asyncio
    async def test_concurrent_publishers(self, topic, invoke_context):
        # Multiple publishers publishing concurrently
        async def publisher(pub_id: int):
            messages = [
                Message(role="user", content=f"Message from publisher {pub_id}")
            ]
            return await topic.a_publish_data(
                invoke_context=invoke_context,
                publisher_name=f"publisher{pub_id}",
                publisher_type="test_publisher",
                data=messages,
                consumed_events=[],
            )

        # Run publishers concurrently
        events = await asyncio.gather(
            publisher(1),
            publisher(2),
            publisher(3),
            publisher(4),
            publisher(5),
        )

        # All events should be published
        assert all(event is not None for event in events)
        assert topic.event_cache.num_events() == 5

        # Consumer should get all events
        consumed = await topic.a_consume("consumer")
        assert len(consumed) == 5

    def test_output_topic_integration(
        self, output_topic, invoke_context, sample_messages
    ):
        # Test with OutputTopic which creates OutputTopicEvent
        event = output_topic.publish_data(
            invoke_context=invoke_context,
            publisher_name="output_publisher",
            publisher_type="test_publisher",
            data=sample_messages,
            consumed_events=[],
        )

        assert isinstance(event, OutputTopicEvent)
        assert output_topic.event_cache.num_events() == 1

        # Consume the output event
        consumed = output_topic.consume("consumer1")
        assert len(consumed) == 1
        assert isinstance(consumed[0], OutputTopicEvent)

    def test_publish_event_handler(self, invoke_context, sample_messages):
        # Track published events
        published_events = []

        def event_handler(event: PublishToTopicEvent):
            published_events.append(event)

        # Create topic with event handler
        topic = Topic(
            name="handler_topic",
            publish_event_handler=event_handler,
        )

        # Publish events
        for i in range(3):
            topic.publish_data(
                invoke_context=invoke_context,
                publisher_name=f"publisher{i}",
                publisher_type="test_publisher",
                data=sample_messages,
                consumed_events=[],
            )

        # Verify handler was called
        assert len(published_events) == 3
        assert all(isinstance(e, PublishToTopicEvent) for e in published_events)

    @pytest.mark.asyncio
    async def test_commit_functionality(self, topic, invoke_context, sample_messages):
        # Publish multiple events
        for i in range(5):
            await topic.a_publish_data(
                invoke_context=invoke_context,
                publisher_name=f"publisher{i}",
                publisher_type="test_publisher",
                data=sample_messages,
                consumed_events=[],
            )

        # Consume some events
        consumed = await topic.a_consume("consumer1")
        assert len(consumed) == 5

        # Commit at offset 3
        await topic.a_commit("consumer1", 3)
        assert topic.event_cache._committed["consumer1"] == 3

    def test_topic_serialization(self, topic):
        # Test to_dict method
        topic_dict = topic.to_dict()
        assert topic_dict["name"] == "test_topic"
        assert topic_dict["type"] == "Topic"
        assert "condition" in topic_dict

    @pytest.mark.asyncio
    async def test_async_reset(self, topic, invoke_context, sample_messages):
        # Add events
        for i in range(3):
            await topic.a_publish_data(
                invoke_context=invoke_context,
                publisher_name=f"publisher{i}",
                publisher_type="test_publisher",
                data=sample_messages,
                consumed_events=[],
            )

        # Consume some
        await topic.a_consume("consumer1")

        # Async reset
        await topic.a_reset()

        # Verify reset
        assert topic.event_cache.num_events() == 0
        assert not topic.can_consume("consumer1")

    def test_consumed_events_tracking(self, topic, invoke_context, sample_messages):
        # Create some consumed events
        consumed_events = []
        for i in range(2):
            consumed_event = ConsumeFromTopicEvent(
                event_id=f"consumed-{i}",
                topic_name="previous_topic",
                consumer_name="node1",
                consumer_type="test_node",
                offset=i,
                data=sample_messages,
                invoke_context=invoke_context,
                timestamp=datetime.now(),
            )
            consumed_events.append(consumed_event)

        # Publish with consumed events
        event = topic.publish_data(
            invoke_context=invoke_context,
            publisher_name="publisher1",
            publisher_type="test_publisher",
            data=sample_messages,
            consumed_events=consumed_events,
        )

        # Verify consumed event IDs are tracked
        assert len(event.consumed_event_ids) == 2
        assert "consumed-0" in event.consumed_event_ids
        assert "consumed-1" in event.consumed_event_ids

    def test_add_event_filtering(self, topic):
        # Try to add a ConsumeFromTopicEvent (should be ignored)
        consume_event = ConsumeFromTopicEvent(
            event_id="consume-1",
            topic_name="test_topic",
            consumer_name="consumer1",
            consumer_type="test_consumer",
            offset=0,
            data=[Message(role="user", content="test")],
            invoke_context=InvokeContext(
                conversation_id="test",
                invoke_id="test",
                assistant_request_id="test",
            ),
            timestamp=datetime.now(),
        )

        # add_event should not add ConsumeFromTopicEvent
        topic.add_event(consume_event)
        assert topic.event_cache.num_events() == 0

        # But PublishToTopicEvent should be added
        publish_event = PublishToTopicEvent(
            event_id="publish-1",
            topic_name="test_topic",
            offset=0,
            publisher_name="publisher",
            publisher_type="test_publisher",
            consumed_event_ids=[],
            invoke_context=InvokeContext(
                conversation_id="test",
                invoke_id="test",
                assistant_request_id="test",
            ),
            data=[Message(role="user", content="test")],
            timestamp=datetime.now(),
        )
        topic.add_event(publish_event)
        assert topic.event_cache.num_events() == 1
