import asyncio
from typing import List

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
    ):
        self.output_topics = output_topics
        self.consumer_name = consumer_name
        self.tracker = tracker
        self.queue: asyncio.Queue[TopicEvent] = asyncio.Queue()
        self._listener_tasks: List[asyncio.Task] = []
        self._stopped = False

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
                for event in events:
                    await self.queue.put(event)
                # Mark messages as committed when they reach the output queue
                if events:
                    logger.debug(f"Output listener: consumed {len(events)} events from {topic.name}")
                    self.tracker.on_messages_committed(len(events), source=f"output_listener:{topic.name}")
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Output listener error for {topic.name}: {e}")
                await asyncio.sleep(0.1)

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
            if check_count % 20 == 0:  # Log every ~10 seconds (20 * 0.5s)
                logger.debug(
                    f"AsyncOutputQueue: still waiting - "
                    f"queue_empty={self.queue.empty()}, "
                    f"tracker_metrics={self.tracker.get_metrics()}"
                )
            # Fast path: queue has items
            if not self.queue.empty():
                try:
                    return self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            # Check for completion (natural quiescence or force stop)
            if self.tracker.should_terminate and self.queue.empty():
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
                    return queue_task.result()
                except asyncio.QueueEmpty:
                    continue

            # Quiescence or force stop detected
            if self.tracker.should_terminate and self.queue.empty():
                raise StopAsyncIteration