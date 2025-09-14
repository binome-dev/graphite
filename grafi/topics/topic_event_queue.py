from abc import ABC
from abc import abstractmethod
from typing import List
from typing import Optional

from grafi.common.events.topic_events.topic_event import TopicEvent


class TopicEventQueue(ABC):
    """
    Abstract interface for topic event queue implementations.

    Can be implemented with different storage backends such as:
    - In-memory (current implementation)
    - Redis (for distributed systems with persistence)
    - Kafka (for high-throughput streaming)
    """

    @abstractmethod
    async def a_put(self, event: TopicEvent) -> TopicEvent:
        """
        Append an event to the queue.

        Args:
            event: The topic event to append

        Returns:
            The event with its offset set
        """
        pass

    @abstractmethod
    async def a_fetch(
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
            timeout: Optional timeout in seconds to wait for new events

        Returns:
            List of fetched events, empty if timeout or no new events
        """
        pass

    @abstractmethod
    async def a_commit_to(self, consumer_id: str, offset: int) -> None:
        """
        Commit all offsets up to and including the specified offset.

        Args:
            consumer_id: Unique identifier for the consumer
            offset: The offset to commit up to
        """
        pass

    @abstractmethod
    async def a_reset(self) -> None:
        """
        Reset the queue to its initial state.
        Clears all events and consumer offsets.
        """
        pass

    @abstractmethod
    async def a_can_consume(self, consumer_id: str) -> bool:
        """
        Check if there are events available for consumption by a consumer.

        Args:
            consumer_id: Unique identifier for the consumer

        Returns:
            True if there are unconsumed events, False otherwise
        """
        pass
