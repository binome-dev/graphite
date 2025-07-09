import inspect
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Self
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from grafi.common.containers.container import container
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages


AGENT_INPUT_TOPIC = "agent_input_topic"
HUMAN_REQUEST_TOPIC = "human_request_topic"

AGENT_RESERVED_TOPICS = [
    AGENT_INPUT_TOPIC,
    HUMAN_REQUEST_TOPIC,
]

# Topic cache configuration
DEFAULT_MAX_CACHE_SIZE = 1000  # Maximum number of events to keep in cache


class TopicEventCache:
    """
    Simple FIFO cache for topic events with count limit only.
    """

    def __init__(self, max_size: int = DEFAULT_MAX_CACHE_SIZE):
        self.max_size = max_size
        self._cache: Dict[int, TopicEvent] = {}
        self._insertion_order: List[int] = []  # Track insertion order for FIFO

    def _evict_fifo(self) -> None:
        """Evict approximately 20% of cache items when over the size limit."""
        if len(self._cache) <= self.max_size:
            return

        # Calculate how many items to remove (20% of current cache size, minimum 1)
        items_to_remove = max(1, int(len(self._cache) * 0.2))

        # Remove the oldest items
        for _ in range(min(items_to_remove, len(self._insertion_order))):
            if not self._insertion_order:
                break
            oldest_offset = self._insertion_order.pop(0)
            if oldest_offset in self._cache:
                self._cache.pop(oldest_offset)

    def get(self, offset: int) -> Optional[TopicEvent]:
        """Get an event by offset."""
        return self._cache.get(offset)

    def put(self, offset: int, event: TopicEvent) -> None:
        """Add or update an event in the cache."""
        if offset not in self._cache:
            # New entry - add to insertion order
            self._insertion_order.append(offset)

        self._cache[offset] = event

        # Evict if necessary
        self._evict_fifo()

    def get_range(self, start_offset: int, end_offset: int) -> List[TopicEvent]:
        """Get a range of events from the cache."""
        events = []
        for offset in range(start_offset, end_offset):
            event = self.get(offset)
            if event:
                events.append(event)
        return events

    def clear(self) -> None:
        """Clear all cached events."""
        self._cache.clear()
        self._insertion_order.clear()

    def __len__(self) -> int:
        return len(self._cache)


class TopicBase(BaseModel):
    """
    Represents a topic in a message queue system.
    Manages both publishing and consumption of message event IDs using a FIFO cache.
    - name: string (the topic's name)
    - condition: function to determine if a message should be published
    - event_cache: FIFO cache for recently accessed events
    - total_published: total number of events published to this topic
    - consumption_offsets: a mapping from node name -> how many events that node has consumed
    """

    name: str = Field(default="")
    condition: Callable[[Messages], bool] = Field(default=lambda _: True)
    consumption_offsets: Dict[str, int] = {}
    event_cache: TopicEventCache = Field(default_factory=TopicEventCache)
    total_published: int = Field(default=0)
    publish_event_handler: Optional[Callable] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def publish_data(
        self,
        invoke_context: InvokeContext,
        publisher_name: str,
        publisher_type: str,
        data: Messages,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> PublishToTopicEvent:
        """
        Publish data to the topic if it meets the condition.
        """
        raise NotImplementedError(
            "Method 'publish_data' must be implemented in subclasses."
        )

    def _retrieve_events_from_store(
        self, start_offset: int, end_offset: int
    ) -> List[TopicEvent]:
        """
        Retrieve events from the event store for the given offset range.
        This method should be overridden by subclasses that need specific event store queries.
        """

        # Generate list of offsets to retrieve
        offsets = list(range(start_offset, end_offset))
        if not offsets:
            return []

        try:
            events = container.event_store.get_topic_events(self.name, offsets)
            return [
                event
                for event in events
                if isinstance(event, (PublishToTopicEvent, OutputTopicEvent))
            ]

        except Exception:
            # If event store is not available or fails, return empty list
            return []

    def get_events_by_offset_range(
        self, start_offset: int, end_offset: int
    ) -> List[TopicEvent]:
        """
        Get events in the specified offset range, retrieving from cache first,
        then from event store if necessary.
        """
        events = []

        # First, try to get events from cache
        cached_events = self.event_cache.get_range(start_offset, end_offset)
        cached_offsets = {event.offset for event in cached_events}

        # Add cached events to result
        events.extend(cached_events)

        # Find missing offsets
        missing_offsets = []
        for offset in range(start_offset, end_offset):
            if offset not in cached_offsets:
                missing_offsets.append(offset)

        if missing_offsets:
            # Retrieve missing events from event store
            missing_start = min(missing_offsets)
            missing_end = max(missing_offsets) + 1
            store_events = self._retrieve_events_from_store(missing_start, missing_end)

            # Cache the retrieved events and add to result
            for event in store_events:
                if event.offset in missing_offsets:
                    self.event_cache.put(event.offset, event)
                    events.append(event)

        # Sort by offset and return
        events.sort(key=lambda e: e.offset)
        return events

    def can_consume(self, consumer_name: str) -> bool:
        """
        Checks whether the given node can consume any new/unread messages
        from this topic (i.e., if there are event IDs that the node hasn't
        already consumed).
        """
        already_consumed = self.consumption_offsets.get(consumer_name, 0)
        return already_consumed < self.total_published

    def consume(self, consumer_name: str) -> List[PublishToTopicEvent]:
        """
        Retrieve new/unconsumed messages for the given node by fetching them
        from the cache or event store. Once retrieved, the node's
        consumption offset is updated so these messages won't be retrieved again.

        :param consumer_name: A unique identifier for the consuming node.
        :return: A list of new messages that were not yet consumed by this node.
        """
        already_consumed = self.consumption_offsets.get(consumer_name, 0)

        if already_consumed >= self.total_published:
            return []

        # Get the new events using the offset range
        new_events = self.get_events_by_offset_range(
            already_consumed, self.total_published
        )

        # Update the offset
        self.consumption_offsets[consumer_name] = self.total_published

        # Filter to only return PublishToTopicEvent instances for backward compatibility
        return [
            event
            for event in new_events
            if isinstance(event, (PublishToTopicEvent, OutputTopicEvent))
        ]

    def reset(self) -> None:
        """
        Reset the topic to its initial state.
        """
        self.event_cache.clear()
        self.consumption_offsets = {}
        self.total_published = 0

    def restore_topic(self, topic_event: TopicEvent) -> None:
        """
        Restore a topic from a topic event.
        """
        if isinstance(topic_event, PublishToTopicEvent) or isinstance(
            topic_event, OutputTopicEvent
        ):
            self.event_cache.put(topic_event.offset, topic_event)
            # Update total_published to the highest offset + 1
            self.total_published = max(self.total_published, topic_event.offset + 1)
        elif isinstance(topic_event, ConsumeFromTopicEvent):
            self.consumption_offsets[topic_event.consumer_name] = topic_event.offset + 1

    def add_event(self, event: TopicEvent) -> None:
        """
        Add an event to the topic cache and update total_published.
        This method should be used by subclasses when publishing events.
        """
        if isinstance(event, (PublishToTopicEvent, OutputTopicEvent)):
            # Ensure the offset is set correctly
            if event.offset == -1 or event.offset is None:
                event.offset = self.total_published

            self.event_cache.put(event.offset, event)
            self.total_published = max(self.total_published, event.offset + 1)

    def get_event_by_offset(self, offset: int) -> Optional[TopicEvent]:
        """
        Get a single event by its offset.
        """
        # First try cache
        cached_event = self.event_cache.get(offset)
        if cached_event:
            return cached_event

        # If not in cache, try to retrieve from event store
        events = self._retrieve_events_from_store(offset, offset + 1)
        if events:
            event = events[0]
            self.event_cache.put(offset, event)
            return event

        return None

    def serialize_callable(self) -> dict:
        """
        Serialize the condition field. If it's a function, return the function name.
        If it's a lambda, return the source code.
        """
        if callable(self.condition):
            if inspect.isfunction(self.condition):
                if self.condition.__name__ == "<lambda>":
                    # It's a lambda, extract source code
                    try:
                        source = inspect.getsource(self.condition).strip()
                    except (OSError, TypeError):
                        source = "<unable to retrieve source>"
                    return {"type": "lambda", "code": source}
                else:
                    # It's a regular function, return its name
                    return {"type": "function", "name": self.condition.__name__}
            elif inspect.isbuiltin(self.condition):
                return {"type": "builtin", "name": self.condition.__name__}
            elif hasattr(self.condition, "__call__"):
                # Handle callable objects
                return {
                    "type": "callable_object",
                    "class_name": self.condition.__class__.__name__,
                }
        return {"type": "unknown"}

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the topic to a dictionary representation.
        """
        return {
            "name": self.name,
            "condition": self.serialize_callable(),
            "total_published": self.total_published,
            "cache_size": len(self.event_cache),
        }


T_T = TypeVar("T_T", bound=TopicBase)


class TopicBaseBuilder(BaseBuilder[T_T]):
    def name(self, name: str) -> Self:
        if name in AGENT_RESERVED_TOPICS:
            raise ValueError(f"Topic name '{name}' is reserved for the agent.")
        self.kwargs["name"] = name
        return self

    def condition(self, condition: Callable[[Messages], bool]) -> Self:
        self.kwargs["condition"] = condition
        return self

    def cache_config(self, max_size: int = DEFAULT_MAX_CACHE_SIZE) -> Self:
        """Configure the event cache count limit."""
        self.kwargs["event_cache"] = TopicEventCache(max_size=max_size)
        return self
