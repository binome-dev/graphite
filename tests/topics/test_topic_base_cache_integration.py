import pytest

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_base import TopicBaseBuilder


class MockTopicWithCache(TopicBase):
    """A mock topic that implements the abstract methods for testing cache integration."""

    @classmethod
    def builder(cls):
        return TopicBaseBuilder(cls)

    def publish_data(
        self, invoke_context, publisher_name, publisher_type, data, consumed_events
    ):
        event = PublishToTopicEvent(
            event_id="test_event",
            topic_name=self.name,
            offset=self.total_published,
            publisher_name=publisher_name,
            publisher_type=publisher_type,
            consumed_event_ids=[],
            invoke_context=invoke_context,
            data=data,
        )
        self.add_event(event)
        return event


class TestTopicBaseCacheIntegration:
    @pytest.fixture
    def sample_invoke_context(self):
        return InvokeContext(
            user_id="test_user",
            conversation_id="test_conversation",
            invoke_id="test_invoke",
            assistant_request_id="test_assistant_request",
        )

    @pytest.fixture
    def topic_with_cache(self):
        """Create a topic with a small cache for testing."""
        return MockTopicWithCache(name="test_topic", event_cache__max_size=3)

    def test_cache_configuration(self):
        """Test configuring cache size via builder."""
        topic = (
            MockTopicWithCache.builder()
            .name("test_topic")
            .cache_config(max_size=50)
            .build()
        )
        assert topic.event_cache.max_size == 50

    def test_add_event_to_cache(self, topic_with_cache, sample_invoke_context):
        """Test that add_event properly stores events in cache."""
        event = PublishToTopicEvent(
            event_id="test_event_1",
            topic_name="test_topic",
            offset=0,
            publisher_name="test_publisher",
            publisher_type="test_type",
            consumed_event_ids=[],
            invoke_context=sample_invoke_context,
            data=[Message(role="user", content="test")],
        )

        topic_with_cache.add_event(event)

        # Event should be in cache
        assert topic_with_cache.event_cache.get(0) == event
        assert topic_with_cache.total_published == 1
        assert len(topic_with_cache.event_cache) == 1

    def test_get_event_by_offset_from_cache(
        self, topic_with_cache, sample_invoke_context
    ):
        """Test getting event by offset from cache."""
        event = PublishToTopicEvent(
            event_id="test_event_1",
            topic_name="test_topic",
            offset=0,
            publisher_name="test_publisher",
            publisher_type="test_type",
            consumed_event_ids=[],
            invoke_context=sample_invoke_context,
            data=[Message(role="user", content="test")],
        )

        topic_with_cache.add_event(event)

        # Should get event from cache
        retrieved_event = topic_with_cache.get_event_by_offset(0)
        assert retrieved_event == event

    def test_get_event_by_offset_from_cache_only(
        self, topic_with_cache, sample_invoke_context
    ):
        """Test getting event by offset from cache when event store is not involved."""
        event = PublishToTopicEvent(
            event_id="test_event_1",
            topic_name="test_topic",
            offset=0,
            publisher_name="test_publisher",
            publisher_type="test_type",
            consumed_event_ids=[],
            invoke_context=sample_invoke_context,
            data=[Message(role="user", content="test")],
        )

        topic_with_cache.add_event(event)

        # Should get event from cache
        retrieved_event = topic_with_cache.get_event_by_offset(0)
        assert retrieved_event == event

        # Non-existent event should return None
        assert topic_with_cache.get_event_by_offset(999) is None

    def test_get_events_by_offset_range_cache_hit(
        self, topic_with_cache, sample_invoke_context
    ):
        """Test getting events by range when all are in cache."""
        events = []
        for i in range(3):
            event = PublishToTopicEvent(
                event_id=f"test_event_{i}",
                topic_name="test_topic",
                offset=i,
                publisher_name="test_publisher",
                publisher_type="test_type",
                consumed_event_ids=[],
                invoke_context=sample_invoke_context,
                data=[Message(role="user", content=f"test {i}")],
            )
            events.append(event)
            topic_with_cache.add_event(event)

        # Get range from cache
        retrieved_events = topic_with_cache.get_events_by_offset_range(0, 3)

        assert len(retrieved_events) == 3
        assert retrieved_events == events

    def test_get_events_by_offset_range_all_cached(
        self, topic_with_cache, sample_invoke_context
    ):
        """Test getting events by range when all events are in cache."""
        # Add one event to cache
        cached_event = PublishToTopicEvent(
            event_id="cached_event",
            topic_name="test_topic",
            offset=0,
            publisher_name="test_publisher",
            publisher_type="test_type",
            consumed_event_ids=[],
            invoke_context=sample_invoke_context,
            data=[Message(role="user", content="cached")],
        )
        topic_with_cache.add_event(cached_event)

        # Get range with only cached events
        retrieved_events = topic_with_cache.get_events_by_offset_range(0, 1)

        # Should get the cached event
        assert len(retrieved_events) == 1
        assert retrieved_events[0] == cached_event

        # Get range that includes non-existent events
        retrieved_events_2 = topic_with_cache.get_events_by_offset_range(0, 5)
        assert len(retrieved_events_2) == 1  # Only the one cached event
        assert retrieved_events_2[0] == cached_event

    def test_consume_with_cache_integration(
        self, topic_with_cache, sample_invoke_context
    ):
        """Test that consume method works with the cache."""
        # Add some events
        for i in range(3):
            event = PublishToTopicEvent(
                event_id=f"test_event_{i}",
                topic_name="test_topic",
                offset=i,
                publisher_name="test_publisher",
                publisher_type="test_type",
                consumed_event_ids=[],
                invoke_context=sample_invoke_context,
                data=[Message(role="user", content=f"test {i}")],
            )
            topic_with_cache.add_event(event)

        # Consumer should get all events
        consumed_events = topic_with_cache.consume("consumer_1")
        assert len(consumed_events) == 3

        # Consumer offset should be updated
        assert topic_with_cache.consumption_offsets["consumer_1"] == 3

        # Second consume should return empty
        consumed_events_2 = topic_with_cache.consume("consumer_1")
        assert len(consumed_events_2) == 0

    def test_cache_size_limit_integration(self, sample_invoke_context):
        """Test that cache size limits work with normal topic operations."""
        topic = MockTopicWithCache(name="test_topic")
        topic.event_cache = topic.event_cache.__class__(max_size=2)  # Very small cache

        # Add more events than cache can hold
        for i in range(5):
            event = PublishToTopicEvent(
                event_id=f"test_event_{i}",
                topic_name="test_topic",
                offset=i,
                publisher_name="test_publisher",
                publisher_type="test_type",
                consumed_event_ids=[],
                invoke_context=sample_invoke_context,
                data=[Message(role="user", content=f"test {i}")],
            )
            topic.add_event(event)

        # Cache should not exceed max size
        assert len(topic.event_cache) <= 2

        # Most recent events should still be available
        assert topic.event_cache.get(4) is not None  # Latest event

        # total_published should still be correct
        assert topic.total_published == 5

    def test_restore_topic_with_cache(self, topic_with_cache, sample_invoke_context):
        """Test that restore_topic properly adds events to cache."""
        event = PublishToTopicEvent(
            event_id="restored_event",
            topic_name="test_topic",
            offset=10,
            publisher_name="test_publisher",
            publisher_type="test_type",
            consumed_event_ids=[],
            invoke_context=sample_invoke_context,
            data=[Message(role="user", content="restored")],
        )

        topic_with_cache.restore_topic(event)

        # Event should be in cache
        assert topic_with_cache.event_cache.get(10) == event
        assert topic_with_cache.total_published == 11  # max(0, 10 + 1)
