from unittest.mock import Mock

import pytest

from grafi.common.topics.topic_base import TopicEventCache


class TestTopicEventCache:
    @pytest.fixture
    def cache(self):
        """Create a TopicEventCache with small max_size for testing."""
        return TopicEventCache(max_size=3)

    @pytest.fixture
    def sample_events(self):
        """Create sample events for testing."""
        events = []
        for i in range(5):
            event = Mock()
            event.offset = i
            event.event_id = f"event_{i}"
            events.append(event)
        return events

    def test_cache_creation(self):
        """Test creating a cache with default and custom sizes."""
        # Default size
        cache = TopicEventCache()
        assert cache.max_size == 1000
        assert len(cache) == 0

        # Custom size
        cache = TopicEventCache(max_size=50)
        assert cache.max_size == 50
        assert len(cache) == 0

    def test_put_and_get(self, cache, sample_events):
        """Test putting and getting events from cache."""
        # Put some events
        cache.put(0, sample_events[0])
        cache.put(1, sample_events[1])

        # Get events
        assert cache.get(0) == sample_events[0]
        assert cache.get(1) == sample_events[1]
        assert cache.get(2) is None  # Not in cache

        assert len(cache) == 2

    def test_get_range(self, cache, sample_events):
        """Test getting a range of events."""
        # Put events with gaps
        cache.put(0, sample_events[0])
        cache.put(2, sample_events[2])
        cache.put(4, sample_events[4])

        # Get range
        events = cache.get_range(0, 5)

        # Should only return events that exist in cache
        assert len(events) == 3
        assert sample_events[0] in events
        assert sample_events[2] in events
        assert sample_events[4] in events

    def test_clear(self, cache, sample_events):
        """Test clearing the cache."""
        cache.put(0, sample_events[0])
        cache.put(1, sample_events[1])

        assert len(cache) == 2

        cache.clear()

        assert len(cache) == 0
        assert cache.get(0) is None
        assert cache.get(1) is None

    def test_eviction_fifo(self, cache, sample_events):
        """Test FIFO eviction when cache exceeds max_size."""
        # Fill cache to max capacity (3)
        cache.put(0, sample_events[0])
        cache.put(1, sample_events[1])
        cache.put(2, sample_events[2])

        assert len(cache) == 3
        assert cache.get(0) == sample_events[0]
        assert cache.get(1) == sample_events[1]
        assert cache.get(2) == sample_events[2]

        # Add one more event, should trigger eviction
        cache.put(3, sample_events[3])

        # Cache should have evicted some old events
        assert len(cache) <= 3  # Should not exceed max_size

        # The newest event should still be there
        assert cache.get(3) == sample_events[3]

    def test_update_existing_event(self, cache, sample_events):
        """Test updating an existing event in cache."""
        cache.put(0, sample_events[0])
        assert cache.get(0) == sample_events[0]

        # Update with a different event at same offset
        new_event = Mock()
        new_event.offset = 0
        new_event.event_id = "updated_event"

        cache.put(0, new_event)

        # Should have the updated event
        assert cache.get(0) == new_event
        assert len(cache) == 1  # Size should remain the same

    def test_large_cache_operations(self):
        """Test cache operations with larger data set."""
        cache = TopicEventCache(max_size=100)

        # Add many events
        events = []
        for i in range(150):  # More than max_size
            event = Mock()
            event.offset = i
            event.event_id = f"event_{i}"
            events.append(event)
            cache.put(i, event)

        # Cache should not exceed max_size
        assert len(cache) <= 100

        # Recent events should still be available
        for i in range(140, 150):  # Last 10 events
            assert cache.get(i) is not None

    def test_get_range_with_empty_cache(self, cache):
        """Test getting range from empty cache."""
        events = cache.get_range(0, 10)
        assert events == []

    def test_get_range_no_overlap(self, cache, sample_events):
        """Test getting range that doesn't overlap with cached events."""
        cache.put(0, sample_events[0])
        cache.put(1, sample_events[1])

        # Request range that doesn't overlap
        events = cache.get_range(5, 10)
        assert events == []
