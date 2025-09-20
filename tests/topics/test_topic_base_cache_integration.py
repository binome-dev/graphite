import asyncio
from datetime import datetime

import pytest

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.queue_impl.in_mem_topic_event_queue import TopicEventQueue
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic


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
        assert isinstance(topic.event_queue, TopicEventQueue)
        assert topic.event_queue.id is not None

    @pytest.mark.asyncio
    async def test_publish_and_consume_single_event(
        self, topic: Topic, invoke_context, sample_messages
    ):
        # Publish an event
        event = await topic.a_publish_data(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                publisher_name="publisher1",
                publisher_type="test_publisher",
                data=sample_messages,
                consumed_event_ids=[],
            )
        )

        assert event is not None
        assert event.name == "test_topic"
        assert event.data == sample_messages

        # Consume the event
        assert await topic.a_can_consume("consumer1")
        consumed_events = await topic.a_consume("consumer1")
        assert len(consumed_events) == 1
        assert consumed_events[0] == event

        # Cannot consume again
        assert not await topic.a_can_consume("consumer1")

    @pytest.mark.asyncio
    async def test_multiple_consumers(
        self, topic: Topic, invoke_context, sample_messages
    ):
        # Publish an event
        event = await topic.a_publish_data(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                publisher_name="publisher1",
                publisher_type="test_publisher",
                data=sample_messages,
                consumed_event_ids=[],
            )
        )

        # Multiple consumers can consume the same event
        consumed1 = await topic.a_consume("consumer1")
        consumed2 = await topic.a_consume("consumer2")

        assert len(consumed1) == 1
        assert len(consumed2) == 1
        assert consumed1[0] == event
        assert consumed2[0] == event

        # Each consumer maintains its own offset
        assert not await topic.a_can_consume("consumer1")
        assert not await topic.a_can_consume("consumer2")

    @pytest.mark.asyncio
    async def test_conditional_publishing(self, invoke_context):
        # Create topic with condition
        topic = Topic(
            name="conditional_topic",
            condition=lambda messages: any(m.role == "user" for m in messages),
        )

        # Message that meets condition
        user_messages = [Message(role="user", content="Hello")]
        event1 = await topic.a_publish_data(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                publisher_name="publisher1",
                publisher_type="test_publisher",
                data=user_messages,
                consumed_event_ids=[],
            )
        )
        assert event1 is not None

        # Message that doesn't meet condition
        assistant_messages = [Message(role="assistant", content="Hi")]
        event2 = await topic.a_publish_data(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                publisher_name="publisher1",
                publisher_type="test_publisher",
                data=assistant_messages,
                consumed_event_ids=[],
            )
        )
        assert event2 is None

        # Only one event should be in cache

    @pytest.mark.asyncio
    async def test_reset_functionality(
        self, topic: Topic, invoke_context, sample_messages
    ):
        # Publish some events
        for i in range(3):
            await topic.a_publish_data(
                PublishToTopicEvent(
                    invoke_context=invoke_context,
                    publisher_name=f"publisher{i}",
                    publisher_type="test_publisher",
                    data=sample_messages,
                    consumed_event_ids=[],
                )
            )

        # Consume some events
        await topic.a_consume("consumer1")
        assert topic.event_queue._consumed["consumer1"] > 0

        # Reset the topic
        await topic.a_reset()

        # Verify everything is cleared
        assert not await topic.a_can_consume("consumer1")

    @pytest.mark.asyncio
    async def test_async_publish_and_consume(
        self, topic: Topic, invoke_context, sample_messages
    ):
        # Async publish
        event = await topic.a_publish_data(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                publisher_name="async_publisher",
                publisher_type="test_publisher",
                data=sample_messages,
                consumed_event_ids=[],
            )
        )

        assert event is not None

        # Async consume
        consumed_events = await topic.a_consume("async_consumer")
        assert len(consumed_events) == 1
        assert consumed_events[0] == event

    @pytest.mark.asyncio
    async def test_async_consume_with_wait(
        self, topic: Topic, invoke_context, sample_messages
    ):
        # Start consumer waiting for events
        consume_task = asyncio.create_task(
            topic.a_consume("waiting_consumer", timeout=1.0)
        )

        # Give it time to start waiting
        await asyncio.sleep(0.1)

        # Publish an event
        event = await topic.a_publish_data(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                publisher_name="publisher",
                publisher_type="test_publisher",
                data=sample_messages,
                consumed_event_ids=[],
            )
        )

        # Consumer should receive the event
        consumed_events = await consume_task
        assert len(consumed_events) == 1
        assert consumed_events[0] == event

    @pytest.mark.asyncio
    async def test_restore_topic_from_publish_event(
        self, topic: Topic, invoke_context, sample_messages
    ):
        # Create a publish event
        event = PublishToTopicEvent(
            event_id="restore-event-1",
            name="test_topic",
            offset=0,
            publisher_name="restore_publisher",
            publisher_type="test_publisher",
            consumed_event_ids=[],
            invoke_context=invoke_context,
            data=sample_messages,
            timestamp=datetime.now(),
        )

        # Restore the topic
        await topic.a_restore_topic(event)

        # Verify event was added to cache
        consumed = await topic.a_consume("consumer1")
        assert len(consumed) == 1
        assert consumed[0] == event

    @pytest.mark.asyncio
    async def test_restore_topic_from_consume_event(
        self, topic: Topic, invoke_context, sample_messages
    ):
        # First, publish an event
        await topic.a_publish_data(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                publisher_name="publisher",
                publisher_type="test_publisher",
                data=sample_messages,
                consumed_event_ids=[],
            )
        )

        # Create a consume event
        consume_event = ConsumeFromTopicEvent(
            event_id="consume-event-1",
            name="test_topic",
            consumer_name="consumer1",
            consumer_type="test_consumer",
            offset=0,
            data=sample_messages,
            invoke_context=invoke_context,
            timestamp=datetime.now(),
        )

        # Restore from consume event
        await topic.a_restore_topic(consume_event)

        # Verify consumer offset was updated
        assert not await topic.a_can_consume("consumer1")  # Already consumed
        assert topic.event_queue._consumed["consumer1"] == 1
        assert topic.event_queue._committed["consumer1"] == 0

    @pytest.mark.asyncio
    async def test_async_restore_topic(
        self, topic: Topic, invoke_context, sample_messages
    ):
        # Create events
        publish_event = PublishToTopicEvent(
            event_id="async-restore-1",
            name="test_topic",
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
            name="test_topic",
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
        assert not await topic.a_can_consume("consumer1")

    @pytest.mark.asyncio
    async def test_concurrent_publishers(self, topic: Topic, invoke_context):
        # Multiple publishers publishing concurrently
        async def publisher(pub_id: int):
            messages = [
                Message(role="user", content=f"Message from publisher {pub_id}")
            ]
            return await topic.a_publish_data(
                PublishToTopicEvent(
                    invoke_context=invoke_context,
                    publisher_name=f"publisher{pub_id}",
                    publisher_type="test_publisher",
                    data=messages,
                    consumed_event_ids=[],
                )
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

        # Consumer should get all events
        consumed = await topic.a_consume("consumer")
        assert len(consumed) == 5

    @pytest.mark.asyncio
    async def test_output_topic_integration(
        self, output_topic: OutputTopic, invoke_context, sample_messages
    ):
        # Test with OutputTopic which creates PublishToTopicEvent
        event = await output_topic.a_publish_data(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                publisher_name="output_publisher",
                publisher_type="test_publisher",
                data=sample_messages,
                consumed_event_ids=[],
            )
        )

        assert isinstance(event, PublishToTopicEvent)

        # Consume the output event
        consumed = await output_topic.a_consume("consumer1")
        assert len(consumed) == 1
        assert isinstance(consumed[0], PublishToTopicEvent)

    @pytest.mark.asyncio
    async def test_commit_functionality(
        self, topic: Topic, invoke_context, sample_messages
    ):
        # Publish multiple events
        for i in range(5):
            await topic.a_publish_data(
                PublishToTopicEvent(
                    invoke_context=invoke_context,
                    publisher_name=f"publisher{i}",
                    publisher_type="test_publisher",
                    data=sample_messages,
                    consumed_event_ids=[],
                )
            )

        # Consume some events
        consumed = await topic.a_consume("consumer1")
        assert len(consumed) == 5

        # Commit at offset 3
        await topic.a_commit("consumer1", 3)
        assert topic.event_queue._committed["consumer1"] == 3

    def test_topic_serialization(self, topic):
        # Test to_dict method
        topic_dict = topic.to_dict()
        assert topic_dict["name"] == "test_topic"
        assert topic_dict["type"] == "Topic"
        assert "condition" in topic_dict

    @pytest.mark.asyncio
    async def test_async_reset(self, topic: Topic, invoke_context, sample_messages):
        # Add events
        for i in range(3):
            await topic.a_publish_data(
                PublishToTopicEvent(
                    invoke_context=invoke_context,
                    publisher_name=f"publisher{i}",
                    publisher_type="test_publisher",
                    data=sample_messages,
                    consumed_event_ids=[],
                )
            )

        # Consume some
        await topic.a_consume("consumer1")

        # Async reset
        await topic.a_reset()

        # Verify reset
        assert not await topic.a_can_consume("consumer1")

    @pytest.mark.asyncio
    async def test_consumed_events_tracking(
        self, topic: Topic, invoke_context, sample_messages
    ):
        # Create some consumed events
        consumed_events = []
        for i in range(2):
            consumed_event = ConsumeFromTopicEvent(
                event_id=f"consumed-{i}",
                name="previous_topic",
                consumer_name="node1",
                consumer_type="test_node",
                offset=i,
                data=sample_messages,
                invoke_context=invoke_context,
                timestamp=datetime.now(),
            )
            consumed_events.append(consumed_event)

        # Publish with consumed events
        event = await topic.a_publish_data(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                publisher_name="publisher1",
                publisher_type="test_publisher",
                data=sample_messages,
                consumed_event_ids=[event.event_id for event in consumed_events],
            )
        )

        # Verify consumed event IDs are tracked
        assert len(event.consumed_event_ids) == 2
        assert "consumed-0" in event.consumed_event_ids
        assert "consumed-1" in event.consumed_event_ids

    @pytest.mark.asyncio
    async def test_add_event_filtering(self, topic: Topic):
        # Try to add a ConsumeFromTopicEvent (should be ignored)
        consume_event = ConsumeFromTopicEvent(
            event_id="consume-1",
            name="test_topic",
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
        await topic.a_add_event(consume_event)

        # But PublishToTopicEvent should be added
        publish_event = PublishToTopicEvent(
            event_id="publish-1",
            name="test_topic",
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
        await topic.a_add_event(publish_event)
