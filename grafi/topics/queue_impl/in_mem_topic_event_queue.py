import asyncio
from collections import defaultdict
from typing import Dict
from typing import List
from typing import Optional

from loguru import logger

from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.default_id import default_id
from grafi.topics.topic_event_queue import TopicEventQueue


class InMemTopicEventQueue(TopicEventQueue):
    """
    In memory message queue where multiple publishers send events to all subscribers.

    A publisher consists in any object who generates message.
    A subscriber consists in any object who can consume messages.
    """

    def __init__(self) -> None:
        self.id: str = default_id
        self._records: List[
            TopicEvent
        ] = (
            []
        )  # contiguous in memory log, persistent all the topic events generated from publishers

        # Per‑consumer cursors
        self._consumed: Dict[str, int] = defaultdict(int)  # next offset to read
        self._committed: Dict[str, int] = defaultdict(
            lambda: -1
        )  # last committed offset

        # For asynchronous operations
        self._cond: asyncio.Condition = (
            asyncio.Condition()
        )  # condition variable for synchronization, all accesses to _records are protected by this condition variable

    # ------------------------------ asynchronous methods ------------------------------
    async def put(self, event: TopicEvent) -> TopicEvent:
        """
        Append a message to the log. Returns the offset of the appended message.
        Implements backpressure when cache is full.
        """
        async with self._cond:
            offset = len(self._records)
            event.offset = offset  # Set the offset for the event
            self._records.append(event)
            self._cond.notify_all()  # wake waiting consumers
            return event

    async def fetch(
        self,
        consumer_id: str,
        offset: Optional[int] = None,
        timeout: Optional[float] = 1.0,
    ) -> List[TopicEvent]:
        """
        Await fresh records newer than the consumer's consumed offset.
        Immediately advances consumed offset to prevent duplicate fetches.
        Returns [] if `timeout` (seconds) elapses with no data.
        If timeout is None or 0, returns immediately with available data (or empty list).
        """

        async with self._cond:
            # If timeout is 0 or None and no data, return immediately
            while not await self.can_consume(consumer_id):
                try:
                    logger.debug(
                        f"Consumer {consumer_id} waiting for new messages with timeout={timeout}"
                    )
                    await asyncio.wait_for(self._cond.wait(), timeout)
                except asyncio.TimeoutError:
                    return []
                except asyncio.CancelledError:
                    # Handle cancellation gracefully
                    logger.debug("Fetch operation was cancelled.")
                    return []

            start = self._consumed[consumer_id]
            if offset is not None:
                end = min(len(self._records), offset + 1)
                batch = self._records[start:end]
            else:
                batch = self._records[start:]

            # Advance consumed offset immediately to prevent duplicate fetches
            self._consumed[consumer_id] += len(batch)

            return batch

    async def commit_to(self, consumer_id: str, offset: int) -> int:
        """Commit all offsets up to and including the specified offset."""
        async with self._cond:
            # Only commit if offset is greater than current committed
            if offset > self._committed[consumer_id]:
                self._committed[consumer_id] = offset

            return self._committed[consumer_id]

    async def reset(self) -> None:
        """
        Reset the queue to its initial state asynchronously.
        """
        async with self._cond:
            self._records = []
            self._consumed = defaultdict(int)
            self._committed = defaultdict(lambda: -1)

    async def can_consume(self, consumer_id: str) -> bool:
        """
        Check if there are events available for consumption by a consumer asynchronously.
        """
        return self._consumed[consumer_id] < len(self._records)
