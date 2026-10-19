from abc import ABC
from abc import abstractmethod
from typing import List
from typing import Optional

from grafi.common.events.topic_events.topic_event import TopicEvent


class TopicEventQueue(ABC):
    """
    Abstract interface for the event queue of a topic used on its own.

    Workflow runs keep their topics in memory and rely on the event store as
    their only durable state, so a workflow rejects a topic whose queue is not
    the in-memory implementation.
    """

    @abstractmethod
    async def put(self, event: TopicEvent) -> TopicEvent:
        """
        Append an event to the queue.

        Args:
            event: The topic event to append

        Returns:
            The event with its offset set
        """
        pass

    @abstractmethod
    async def fetch(
        self,
        consumer_id: str,
        offset: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> List[TopicEvent]:
        """
        Fetch events newer than the consumer's consumed offset.

        Args:
            consumer_id: Unique identifier for the consumer
            offset: Optional specific offset to fetch up to
            timeout: None waits indefinitely, 0 reads without waiting, and a
                positive value bounds the entire wait in seconds.

        Returns:
            List of fetched events, empty on timeout, an empty nonblocking read,
            or when no unread events fall within the requested offset range.
            Cancellation propagates to the caller.

        Implementations must terminate promptly on cancellation, including any
        local cleanup. A cancelled fetch must leave the read cursor unchanged.
        Fetching advances the read cursor, not the committed offset.
        """
        pass

    @abstractmethod
    async def commit_to(self, consumer_id: str, offset: int) -> int:
        """
        Commit all offsets up to and including the specified offset.

        Args:
            consumer_id: Unique identifier for the consumer
            offset: The offset to commit up to
        """
        pass

    @abstractmethod
    async def restore_consumer(self, consumer_id: str, committed_offset: int) -> None:
        """
        Restore a consumer's cursors, without consuming events.

        Marks the consumer as having consumed and committed every offset up to
        and including ``committed_offset``. The next event delivered to this
        consumer is ``committed_offset + 1``: nothing at or before
        ``committed_offset`` is re-delivered, and nothing after it is skipped.

        Unlike :meth:`fetch`, this never blocks and never returns events: it only
        restores cursors (``fetch`` over-advances the consumed cursor by one when
        misused for that).

        Args:
            consumer_id: Unique identifier for the consumer
            committed_offset: Highest offset the consumer had committed
        """
        ...

    @abstractmethod
    async def reset(self) -> None:
        """
        Reset the queue to its initial state.
        Clears all events and consumer offsets.
        """
        pass

    @abstractmethod
    async def can_consume(self, consumer_id: str) -> bool:
        """
        Check if there are events available for consumption by a consumer.

        Args:
            consumer_id: Unique identifier for the consumer

        Returns:
            True if there are unconsumed events, False otherwise
        """
        pass

    async def unconsumed_count(self, consumer_id: str) -> int:
        """
        Exact number of events the consumer has not yet fetched.

        An exact count, not a 0/1 approximation. Optional for a backend: the
        workflow engine does not use it.

        Args:
            consumer_id: Unique identifier for the consumer

        Returns:
            Count of unconsumed events (>= 0).
        """
        raise NotImplementedError
