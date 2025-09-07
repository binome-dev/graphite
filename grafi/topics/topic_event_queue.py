import asyncio
from collections import defaultdict
from typing import Dict
from typing import List
from typing import Optional

from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.default_id import default_id


class TopicEventQueue:
    """
    In memory message queue where multiple publishers send events to all subscribers.

    A publisher consists in any object who generates message.
    A subscriber consists in any object who can consume messages.
    """

    def __init__(self) -> None:
        self.id: str = default_id
        self._records: List[TopicEvent] = (
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

    def reset(self) -> None:
        """
        Reset the topic to its initial state.
        """
        self._records = []
        self._consumed = defaultdict(int)
        self._committed = defaultdict(lambda: -1)
        self._cond = asyncio.Condition()

    def num_events(self) -> int:
        """
        Returns the number of events in the cache.
        """
        return len(self._records)

    # ------------------------------ Synchronous methods ------------------------------

    # ------------------------------------------------------------------
    # Producer
    # ------------------------------------------------------------------
    def put(self, event: TopicEvent) -> TopicEvent:
        offset = len(self._records)
        event.offset = offset  # Set the offset for the event
        self._records.append(event)
        return event

    def can_consume(self, consumer_id: str) -> bool:
        # Can consume if there are records beyond the consumed offset
        return self._consumed[consumer_id] < len(self._records)

    def fetch(
        self,
        consumer_id: str,
        offset: Optional[int] = None,
    ) -> List[TopicEvent]:
        """
        Fetch records newer than the consumer's consumed offset.
        Immediately advances consumed offset to prevent duplicate fetches.
        Returns [] if no new data available.
        """
        if self.can_consume(consumer_id):
            start = self._consumed[consumer_id]
            if offset is not None:
                end = min(len(self._records), offset + 1)
                batch = self._records[start:end]
            else:
                batch = self._records[start:]

            # Advance consumed offset immediately to prevent duplicate fetches
            self._consumed[consumer_id] += len(batch)
            return batch

        return []

    def commit_to(self, consumer_id: str, offset: int) -> int:
        """
        Marks everything up to `offset` as processed/durable
        for this consumer.
        Returns the new committed offset.
        """
        # Only commit if offset is greater than current committed
        if offset > self._committed[consumer_id]:
            self._committed[consumer_id] = offset
        return self._committed[consumer_id]

    # ------------------------------ asynchronous methods ------------------------------
    async def a_put(self, event: TopicEvent) -> TopicEvent:
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

    async def a_fetch(
        self,
        consumer_id: str,
        offset: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> List[TopicEvent]:
        """
        Await fresh records newer than the consumer's consumed offset.
        Immediately advances consumed offset to prevent duplicate fetches.
        Returns [] if `timeout` (seconds) elapses with no data.
        """

        async with self._cond:
            while not self.can_consume(consumer_id):
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout)
                except asyncio.TimeoutError:
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

    async def a_commit_to(self, consumer_id: str, offset: int) -> None:
        """Commit all offsets up to and including the specified offset."""
        async with self._cond:
            # Only commit if offset is greater than current committed
            if offset > self._committed[consumer_id]:
                self._committed[consumer_id] = offset
