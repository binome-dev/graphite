from contextlib import contextmanager
from contextvars import ContextVar
from typing import Annotated
from typing import Any
from typing import ClassVar
from typing import Dict
from typing import Iterator
from typing import List
from typing import Mapping
from typing import Optional
from typing import Self
from typing import TypeVar
from uuid import uuid4

from pydantic import BeforeValidator
from pydantic import Field
from pydantic import PlainSerializer
from pydantic import ValidationInfo

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions.event_exceptions import TopicPublicationError
from grafi.common.manifest import Component
from grafi.common.models.base_builder import BaseBuilder
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue
from grafi.topics.topic_event_queue import TopicEventQueue
from grafi.topics.topic_types import TopicType


class TopicBase(Component):
    """
    A named channel that nodes publish to and subscribe to.

    A topic carries no routing ``condition`` (all routing lives on the node's
    publisher router). In a workflow, each run keeps the topic's events itself
    and builds every publication with ``prepare_publication()``, the hook for
    transforming or validating one. ``publish_data`` and the queue methods are
    for using a topic on its own, through its ``event_queue``.

    - name: string (the topic's name)
    - event_queue: FIFO queue of the topic's events, for use on its own, and
      never saved
    """

    manifest_kind: ClassVar[Optional[str]] = "Topic"

    name: str = Field(default="")
    type: TopicType = Field(default=TopicType.DEFAULT_TOPIC_TYPE)
    event_queue: TopicEventQueue = Field(
        default_factory=InMemTopicEventQueue, exclude=True
    )

    async def publish_data(
        self, publish_event: PublishToTopicEvent
    ) -> PublishToTopicEvent:
        """Create a distinct destination publication from a source emission.

        Each call allocates a new event ID, even for a repeated source event.
        Source lineage is retained in emission_id. ``restore_topic()`` puts a
        stored publication back unchanged instead.
        Always returns the enqueued event: routing already happened on the
        node's publisher router, so a topic never drops an event.
        """
        published = await self.add_event(self.prepare_publication(publish_event))
        if not isinstance(published, PublishToTopicEvent):
            # add_event only returns None for non-publish events, so reaching here
            # means a subclass or queue broke the pure-queue contract.
            raise TopicPublicationError(
                topic_name=self.name,
                message=f"[{self.name}] add_event() did not enqueue the publication",
            )
        return published

    def prepare_publication(
        self, publish_event: PublishToTopicEvent
    ) -> PublishToTopicEvent:
        """Build this topic's publication of a source emission without enqueueing it.

        The copy gets a fresh event ID and records the source in ``emission_id``;
        the source event is left unchanged.
        """
        return publish_event.model_copy(
            update={
                "name": self.name,
                "type": self.type,
                "event_id": uuid4().hex,
                "emission_id": publish_event.event_id,
            },
            deep=True,
        )

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
        Retrieve unread messages for this consumer.
        See :meth:`TopicEventQueue.fetch` for timeout and cancellation behavior.
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
        """Enqueue a publication and return it with its offset set.

        Returns ``None`` for non-publish events, which are not enqueued.
        """
        if isinstance(event, PublishToTopicEvent):
            return await self.event_queue.put(event)
        return None


# The topics of the workflow being loaded, by name, which its nodes name.
_loading_topics: ContextVar[Optional[Dict[str, TopicBase]]] = ContextVar(
    "grafi_loading_topics", default=None
)


@contextmanager
def loading_topics(topics: Dict[str, TopicBase]) -> Iterator[None]:
    """Resolve the topic names loaded in this block to ``topics``."""
    token = _loading_topics.set(topics)
    try:
        yield
    finally:
        _loading_topics.reset(token)


def _topic(value: Any, info: ValidationInfo) -> Any:
    """A topic, from its name: one of the topics of the workflow being loaded
    (see ``EventDrivenWorkflow``), or of the validation context's ``topics``."""
    topics = _loading_topics.get()
    if topics is None:
        topics = (info.context or {}).get("topics", {})
    if isinstance(value, Mapping) and value.get("name") in topics:
        return topics[value["name"]]  # A topic dumped in full: the same one.
    if not isinstance(value, str):
        return value
    if value not in topics:
        raise ValueError(
            f"Unknown topic {value!r}: a topic named in a manifest must be "
            f"one of its workflow's topics ({sorted(topics)})."
        )
    return topics[value]


# A field holding a topic, saved as the topic's name.
TopicRef = Annotated[
    TopicBase,
    PlainSerializer(lambda topic: topic.name, return_type=str, when_used="json"),
    BeforeValidator(_topic),
]


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
