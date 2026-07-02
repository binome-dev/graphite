from typing import Any
from typing import List
from typing import Optional
from typing import Self
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.base_builder import BaseBuilder
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue
from grafi.topics.topic_event_queue import TopicEventQueue
from grafi.topics.topic_types import TopicType


class TopicBase(BaseModel):
    """
    Represents a topic in a message queue system: a pure FIFO queue.

    A topic only stores and delivers events; it carries no routing ``condition``
    (all routing lives on the node's publisher router). ``publish_data`` stamps
    the event with this topic's name/type and enqueues it.

    - name: string (the topic's name)
    - event_queue: FIFO cache for recently accessed events
    """

    name: str = Field(default="")
    type: TopicType = Field(default=TopicType.DEFAULT_TOPIC_TYPE)
    event_queue: TopicEventQueue = Field(default_factory=InMemTopicEventQueue)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def publish_data(
        self, publish_event: PublishToTopicEvent
    ) -> Optional[PublishToTopicEvent]:
        """Stamp the event with this topic's name/type and enqueue it.

        Returns the enqueued event. Routing has already happened on the node's
        publisher router, so a topic never drops an event.
        """
        event = publish_event.model_copy(
            update={
                "name": self.name,
                "type": self.type,
            },
            deep=True,
        )
        return await self.add_event(event)

    async def can_consume(self, consumer_name: str) -> bool:
        """
        Checks whether the given node can consume any new/unread messages
        from this topic (i.e., if there are event IDs that the node hasn't
        already consumed).
        """
        return await self.event_queue.can_consume(consumer_name)

    async def unconsumed_count(self, consumer_name: str) -> int:
        """Number of messages this consumer has not yet consumed from the topic."""
        return await self.event_queue.unconsumed_count(consumer_name)

    async def consume(
        self, consumer_name: str, timeout: Optional[float] = None
    ) -> List[TopicEvent]:
        """
        Asynchronously retrieve new/unconsumed messages for the given node by fetching them
        """
        return await self.event_queue.fetch(consumer_name, timeout=timeout)

    async def commit(self, consumer_name: str, offset: int) -> None:
        await self.event_queue.commit_to(consumer_name, offset)

    async def reset(self) -> None:
        """
        Asynchronously reset the topic to its initial state.
        """
        await self.event_queue.reset()

    async def restore_topic(self, topic_event: TopicEvent) -> None:
        """
        Asynchronously restore a topic from a topic event.
        """
        if isinstance(topic_event, PublishToTopicEvent):
            await self.event_queue.put(topic_event)
        elif isinstance(topic_event, ConsumeFromTopicEvent):
            # Restore the consumer's cursor to the recorded commit point. The
            # next event delivered is topic_event.offset + 1, so the offset
            # immediately after the committed one is not skipped.
            await self.event_queue.restore_consumer(
                consumer_id=topic_event.consumer_name,
                committed_offset=topic_event.offset,
            )

    async def add_event(self, event: TopicEvent) -> Optional[TopicEvent]:
        """
        Asynchronously add an event to the topic cache and update total_published.
        This method should be used by subclasses when publishing events.

        Returns ``None`` for non-publish events (only PublishToTopicEvents are
        appended to the queue).
        """
        if isinstance(event, PublishToTopicEvent):
            return await self.event_queue.put(event)
        return None

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the topic to a dictionary representation.
        """
        return {
            "name": self.name,
            "type": self.type.value,
        }

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "TopicBase":
        """
        Create a TopicBase instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the TopicBase.

        Returns:
            TopicBase: A TopicBase instance created from the dictionary.
        """
        return cls(
            name=data["name"],
            type=data["type"],
        )


T_T = TypeVar("T_T", bound=TopicBase)


class TopicBaseBuilder(BaseBuilder[T_T]):
    """Builder for TopicBase instances."""

    def name(self, name: str) -> Self:
        """Set the topic's unique name.

        Args:
            name: Unique identifier for the topic within a workflow.

        Returns:
            Self for method chaining.
        """
        self.kwargs["name"] = name
        return self

    def type(self, type_name: str) -> Self:
        """Set the topic's type identifier.

        Args:
            type_name: Type classification for the topic.

        Returns:
            Self for method chaining.
        """
        self.kwargs["type"] = type_name
        return self
