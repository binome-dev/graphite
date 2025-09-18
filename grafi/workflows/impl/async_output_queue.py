import asyncio
from typing import AsyncGenerator
from typing import List

from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.topics.topic_base import TopicBase
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker


class AsyncOutputQueue:
    """
    Manages output topics and their listeners for async workflow execution.
    Wraps output_topics, listener_tasks, and tracker functionality.
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
        self.listener_tasks: List[asyncio.Task] = []

    async def start_listeners(self) -> None:
        """Start listener tasks for all output topics."""
        self.listener_tasks = [
            asyncio.create_task(self._output_listener(topic))
            for topic in self.output_topics
        ]

    async def stop_listeners(self) -> None:
        """Stop all listener tasks."""
        for task in self.listener_tasks:
            task.cancel()
        await asyncio.gather(*self.listener_tasks, return_exceptions=True)

    async def _output_listener(self, topic: TopicBase) -> None:
        """
        Streams *matching* records from `topic` into `queue`.
        Exits when the graph is idle *and* the topic has no more unseen data,
        with proper handling for downstream node activation.
        """
        last_activity_count = 0

        while True:
            # waiter 1: "some records arrived"
            topic_task = asyncio.create_task(topic.a_consume(self.consumer_name))
            # waiter 2: "graph just became idle"
            idle_event_waiter = asyncio.create_task(self.tracker.wait_idle_event())

            done, pending = await asyncio.wait(
                {topic_task, idle_event_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )

            # ---- If records arrived -----------------------------------------
            if topic_task in done:
                output_events = topic_task.result()

                for output_event in output_events:
                    await self.queue.put(output_event)

            # ---- Check for workflow completion ----------------
            if idle_event_waiter in done and self.tracker.is_idle():
                current_activity = self.tracker.get_activity_count()

                # If no new activity since last check and no data, we're done
                if (
                    current_activity == last_activity_count
                    and not await topic.a_can_consume(self.consumer_name)
                ):
                    # cancel an unfinished waiter (if any) to avoid warnings
                    for t in pending:
                        t.cancel()
                    break

                last_activity_count = current_activity

            # Cancel the topic task since we're checking idle state
            for t in pending:
                t.cancel()

    def __aiter__(self) -> AsyncGenerator[TopicEvent, None]:
        """Make AsyncOutputQueue async iterable."""
        return self

    async def __anext__(self) -> TopicEvent:
        """Async iteration implementation with idle detection."""
        # two parallel waiters
        while True:
            queue_task = asyncio.create_task(self.queue.get())
            idle_task = asyncio.create_task(self.tracker._idle_event.wait())

            done, pending = await asyncio.wait(
                {queue_task, idle_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Case A: we got a queue item first → stream it
            if queue_task in done:
                idle_task.cancel()
                await asyncio.gather(idle_task, return_exceptions=True)
                return queue_task.result()

            # Case B: pipeline went idle first
            queue_task.cancel()
            await asyncio.gather(queue_task, return_exceptions=True)

            # Give downstream consumers one chance to register activity.
            await asyncio.sleep(0)  # one event‑loop tick

            if self.tracker.is_idle() and self.queue.empty():
                raise StopAsyncIteration
