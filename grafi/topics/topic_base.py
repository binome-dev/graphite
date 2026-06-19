from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Self
from typing import TypeVar

from loguru import logger
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from grafi.common.callable_ref import deserialize_callable
from grafi.common.callable_ref import serialize_callable
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.message import Messages
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue
from grafi.topics.topic_event_queue import TopicEventQueue
from grafi.topics.topic_types import TopicType


def always_true(_: PublishToTopicEvent) -> bool:
    """Default topic condition: publish every event.

    A named module-level function (rather than an inline ``lambda``) so it
    serializes as a tiny import reference instead of inline code.
    """
    return True


def deserialize_condition(
    data: Dict[str, Any],
) -> Callable[[PublishToTopicEvent], bool]:
    """Reconstruct a topic's ``condition`` from its serialized form.

    Centralizes the decoding shared by every topic ``from_dict``. A missing or
    empty condition falls back to :func:`always_true`. Otherwise the value is
    resolved by :func:`~grafi.common.callable_ref.deserialize_callable`, which
    handles references and components (no pickle).
    """
    raw = data.get("condition")
    if raw is None or raw == "":
        return always_true
    return deserialize_callable(
        raw, context=f"topic '{data.get('name', '')}' condition"
    )


class TopicBase(BaseModel):
    """
    Represents a topic in a message queue system.
    Manages both publishing and consumption of message event IDs using a FIFO cache.
    - name: string (the topic's name)
    - condition: function to determine if a message should be published
    - event_queue: FIFO cache for recently accessed events
    - total_published: total number of events published to this topic
    """

    name: str = Field(default="")
    type: TopicType = Field(default=TopicType.DEFAULT_TOPIC_TYPE)
    condition: Callable[[PublishToTopicEvent], bool] = Field(default=always_true)
    event_queue: TopicEventQueue = Field(default_factory=InMemTopicEventQueue)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def publish_data(
        self, publish_event: PublishToTopicEvent
    ) -> Optional[PublishToTopicEvent]:
        """
        Publish data to the topic if it meets the condition.

        Returns the published event, or ``None`` when the topic's condition is
        not met (callers must null-check).
        """
        try:
            condition_met = self.condition(publish_event)
        except (IndexError, KeyError) as e:
            # Expected "not met" signal for conditions that index into data that
            # may legitimately be empty/absent.
            logger.debug(f"[{self.name}] Condition not met ({type(e).__name__}: {e}).")
            condition_met = False
        except Exception as e:
            # An unexpected error in a user condition is almost certainly a bug.
            # Surface it at WARNING (a silent drop here looks identical to a normal
            # routing decision) but still treat as not-met so one faulty condition
            # cannot halt the whole workflow.
            logger.warning(
                f"[{self.name}] Condition raised an unexpected "
                f"{type(e).__name__}: {e}. Treating as not published; "
                "check the topic condition."
            )
            condition_met = False

        if condition_met:
            event = publish_event.model_copy(
                update={
                    "name": self.name,
                    "type": self.type,
                },
                deep=True,
            )
            return await self.add_event(event)
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None

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
            # Fetch the events for the consumer and commit the offset
            await self.event_queue.fetch(
                consumer_id=topic_event.consumer_name, offset=topic_event.offset + 1
            )
            await self.event_queue.commit_to(
                topic_event.consumer_name, topic_event.offset
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
            "condition": serialize_callable(self.condition),
        }

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "TopicBase":
        """
        Create a TopicBase instance from a dictionary representation.

        Args:
            data (dict[str, Any]): A dictionary representation of the TopicBase.

        Returns:
            TopicBase: A TopicBase instance created from the dictionary.

        Note:
            The condition is reconstructed (without pickle) from its import
            reference or CallableComponent config. See
            :mod:`grafi.common.callable_ref`.
        """
        return cls(
            name=data["name"],
            type=data["type"],
            condition=deserialize_condition(data),
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

    def condition(self, condition: Callable[[Messages], bool]) -> Self:
        """Set a condition function that determines when this topic is satisfied.

        Args:
            condition: A callable that takes Messages and returns True
                when the topic's output condition is met.

        Returns:
            Self for method chaining.
        """
        self.kwargs["condition"] = condition
        return self
