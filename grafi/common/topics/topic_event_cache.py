import asyncio
from collections import defaultdict
from typing import Dict
from typing import List
from typing import Optional

from grafi.common.events.topic_events.topic_event import TopicEvent


DEFAULT_MAX_CACHE_SIZE = 1000


class TopicEventCache:
    """
    A single-process, pure-Python component that behaves like a miniature,
    in-memory Kafka partition with concurrent producers and consumers.
    """

    def __init__(self, name: str = ""):
        self.name: str = name
        self._records: List[TopicEvent] = []  # contiguous log

        # Per‑consumer cursors
        self._consumed: Dict[str, int] = defaultdict(int)  # next offset to read
        self._committed: Dict[str, int] = defaultdict(
            lambda: -1
        )  # last committed offset

        # For asynchronous operations
        self._cond: asyncio.Condition = asyncio.Condition()

    def reset(self) -> None:
        """
        Reset the topic to its initial state.
        """
        self._records: List[TopicEvent] = []
        self._consumed: Dict[str, int] = defaultdict(int)
        self._committed: Dict[str, int] = defaultdict(lambda: -1)
        self._cond: asyncio.Condition = asyncio.Condition()

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

    # ------------------------------------------------------------------
    # Consumer helpers
    # ------------------------------------------------------------------
    def _ensure_consumer(self, cid: str) -> None:
        self._consumed.setdefault(cid, 0)
        self._committed.setdefault(cid, -1)

    def can_consume(self, cid: str) -> bool:
        self._ensure_consumer(cid)
        # Can consume if there are records beyond the consumed offset
        return self._consumed[cid] < len(self._records)

    def fetch(
        self,
        cid: str,
        offset: Optional[int] = None,
    ) -> List[TopicEvent]:
        """
        Fetch records newer than the consumer's consumed offset.
        Immediately advances consumed offset to prevent duplicate fetches.
        Returns [] if no new data available.
        """
        self._ensure_consumer(cid)

        if self.can_consume(cid):
            start = self._consumed[cid]
            if offset is not None:
                end = min(len(self._records), offset + 1)
                batch = self._records[start:end]
            else:
                batch = self._records[start:]

            # Advance consumed offset immediately to prevent duplicate fetches
            self._consumed[cid] += len(batch)
            return batch

        return []

    def commit_to(self, cid: str, offset: int) -> int:
        """
        Marks everything up to `offset` as processed/durable
        for this consumer.
        Returns the new committed offset.
        """
        self._ensure_consumer(cid)
        # Only commit if offset is greater than current committed
        if offset > self._committed[cid]:
            self._committed[cid] = offset
        return self._committed[cid]

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
        cid: str,
        offset: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> List[TopicEvent]:
        """
        Await fresh records newer than the consumer's consumed offset.
        Immediately advances consumed offset to prevent duplicate fetches.
        Returns [] if `timeout` (seconds) elapses with no data.
        """
        self._ensure_consumer(cid)

        async with self._cond:

            async def _wait():
                await self._cond.wait()

            while not self.can_consume(cid):
                if timeout is None:
                    await _wait()
                else:
                    try:
                        await asyncio.wait_for(_wait(), timeout)
                    except asyncio.TimeoutError:
                        return []

            start = self._consumed[cid]
            if offset is not None:
                end = min(len(self._records), offset + 1)
                batch = self._records[start:end]
            else:
                batch = self._records[start:]

            # Advance consumed offset immediately to prevent duplicate fetches
            self._consumed[cid] += len(batch)

            return batch

    async def a_commit_to(self, cid: str, offset: int) -> None:
        """Commit all offsets up to and including the specified offset."""
        async with self._cond:
            self._ensure_consumer(cid)
            # Only commit if offset is greater than current committed
            if offset > self._committed[cid]:
                self._committed[cid] = offset
