import asyncio
from typing import Awaitable
from typing import Callable
from typing import List
from typing import Optional

from loguru import logger

from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.topics.topic_base import TopicBase
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker


class AsyncOutputQueue:
    """
    Manages output topics and provides async iteration over output events.

    Simplified: All quiescence detection delegated to AsyncNodeTracker.
    """

    def __init__(
        self,
        output_topics: List[TopicBase],
        consumer_name: str,
        tracker: AsyncNodeTracker,
        progress_possible: Optional[Callable[[], Awaitable[bool]]] = None,
    ):
        self.output_topics = output_topics
        self.consumer_name = consumer_name
        self.tracker = tracker
        # Optional workflow callback: True while progress is still possible
        # (a node is active, an event is still consumable, or some node can
        # invoke). When this stays False while the tracker is non-quiescent, the
        # outstanding deliveries are parked (e.g. an unsatisfied AND-subscription
        # whose other branch never arrived) and iteration ends rather than hangs.
        self._progress_possible = progress_possible
        self._stuck_polls = 0
        self.queue: asyncio.Queue[TopicEvent] = asyncio.Queue()
        self._listener_tasks: List[asyncio.Task] = []
        self._stopped = False
        # First fatal error raised by a listener, surfaced to the consumer via
        # __anext__ (otherwise stop_listeners' gather(return_exceptions=True)
        # would silently swallow it and the workflow would appear to end cleanly).
        self._listener_error: Optional[BaseException] = None

    async def start_listeners(self) -> None:
        """Start listener tasks for all output topics."""
        self._stopped = False
        self._listener_tasks = [
            asyncio.create_task(self._output_listener(topic))
            for topic in self.output_topics
        ]

    async def stop_listeners(self) -> None:
        """Stop all listener tasks."""
        self._stopped = True
        for task in self._listener_tasks:
            task.cancel()
        await asyncio.gather(*self._listener_tasks, return_exceptions=True)
        self._listener_tasks.clear()

    async def _output_listener(self, topic: TopicBase) -> None:
        """
        Forward events to queue and track message consumption.

        When events are consumed from output topics, they've reached their
        destination (the output queue), so we mark them as committed.
        """
        while not self._stopped:
            try:
                events = await topic.consume(self.consumer_name, timeout=0.1)

                if len(events) == 0:
                    # No events fetched within timeout, check if all node quiescence
                    if await self.tracker.should_terminate():
                        break

                for event in events:
                    await self.queue.put(event)
                # Mark messages as committed when they reach the output queue
                if events:
                    logger.debug(
                        f"Output listener: consumed {len(events)} events from {topic.name}"
                    )
                    await self.tracker.on_messages_committed(
                        len(events), source=f"output_listener:{topic.name}"
                    )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Output listener error for {topic.name}: {e}")
                # Record the error and force termination so __anext__ wakes and
                # re-raises it to the consumer instead of it being swallowed.
                if self._listener_error is None:
                    self._listener_error = e
                await self.tracker.force_stop()
                break

    def __aiter__(self) -> "AsyncOutputQueue":
        return self

    async def __anext__(self) -> TopicEvent:
        """
        SIMPLIFIED: Delegates quiescence check entirely to tracker.

        Removed:
        - last_activity_count tracking
        - asyncio.sleep(0) hack
        - duplicated idle detection logic
        """
        check_count = 0
        while True:
            check_count += 1

            # Drain any pending items before surfacing a listener failure, so the
            # caller still receives output produced before the error.
            if self._listener_error is not None and self.queue.empty():
                raise self._listener_error

            # Fast path: queue has items
            if not self.queue.empty():
                try:
                    item = self.queue.get_nowait()
                    self._stuck_polls = 0  # progress made
                    return item
                except asyncio.QueueEmpty:
                    pass

            # Check for completion (natural quiescence or force stop)
            if await self.tracker.should_terminate():
                # Final drain attempt - try to get any remaining items before stopping
                # This avoids race where item is added between empty() check and raising
                try:
                    return self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    raise StopAsyncIteration

            # Wait for queue item or quiescence
            queue_task = asyncio.create_task(self.queue.get())
            quiescent_task = asyncio.create_task(
                self.tracker.wait_for_quiescence(timeout=0.5)
            )

            done, pending = await asyncio.wait(
                {queue_task, quiescent_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Got queue item
            if queue_task in done and not queue_task.cancelled():
                try:
                    item = queue_task.result()
                    self._stuck_polls = 0  # progress made
                    return item
                except asyncio.QueueEmpty:
                    # Task was cancelled as part of normal cleanup; ignore.
                    continue

            # Quiescence or force stop detected
            if await self.tracker.should_terminate():
                # Final drain attempt - try to get any remaining items before stopping
                # This avoids race where item is added between empty() check and raising
                try:
                    return self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    # A listener failure (which also forces termination) must
                    # surface as that error, not a clean end-of-iteration.
                    if self._listener_error is not None:
                        raise self._listener_error
                    raise StopAsyncIteration

            # Not quiescent and no queue item after the wait. If the workflow
            # reports no further progress is possible, the outstanding tracker
            # count is parked work that will never commit, so end iteration
            # instead of looping forever. Require two consecutive idle polls so a
            # node momentarily between consuming its inputs and marking itself
            # active is not mistaken for stuck.
            if self._progress_possible is not None and self.queue.empty():
                if await self._progress_possible():
                    self._stuck_polls = 0
                else:
                    self._stuck_polls += 1
                    if self._stuck_polls >= 2:
                        logger.debug(
                            "Output queue: no progress possible; ending iteration "
                            "(parked deliveries)."
                        )
                        raise StopAsyncIteration
