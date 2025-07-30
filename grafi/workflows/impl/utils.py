import asyncio
from collections import defaultdict
from typing import Dict
from typing import List
from typing import Tuple

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.topics.topic_base import TopicBase
from grafi.nodes.node import Node


def get_async_output_events(events: List[TopicEvent]) -> List[TopicEvent]:
    """
    Process a list of TopicEvents, grouping by topic_name and aggregating streaming messages.

    Args:
        events: List of TopicEvents to process

    Returns:
        List of processed TopicEvents with streaming messages aggregated
    """
    # Group events by topic_name
    events_by_topic: Dict[str, List[TopicEvent]] = {}
    for event in events:
        if event.topic_name not in events_by_topic:
            events_by_topic[event.topic_name] = []
        events_by_topic[event.topic_name].append(event)

    output_events: List[TopicEvent] = []

    for _, topic_events in events_by_topic.items():
        # Separate streaming and non-streaming events
        streaming_events: List[TopicEvent] = []
        non_streaming_events: List[TopicEvent] = []

        for event in topic_events:
            # Check if event.data contains streaming messages
            is_streaming_event = False
            # Handle both single message and list of messages
            messages = event.data
            if messages and len(messages) > 0 and messages[0].is_streaming:
                is_streaming_event = True

            if is_streaming_event:
                streaming_events.append(event)
            else:
                non_streaming_events.append(event)

        # Add non-streaming events as-is
        output_events.extend(non_streaming_events)

        # Aggregate streaming events if any exist
        if streaming_events:
            # Use the first streaming event as the base for creating the aggregated event
            base_event = streaming_events[0]

            # Aggregate content from all streaming messages
            aggregated_content_parts = []
            for event in streaming_events:
                messages = event.data if isinstance(event.data, list) else [event.data]
                for message in messages:
                    if message.content:
                        aggregated_content_parts.append(message.content)
            aggregated_content = "".join(aggregated_content_parts)

            # Create a new message with aggregated content
            # Copy properties from the first message but update content and streaming flag
            first_message = (
                base_event.data
                if isinstance(base_event.data, list)
                else [base_event.data]
            )[0]
            aggregated_message = Message(
                role=first_message.role,
                content=aggregated_content,
                is_streaming=False,  # Aggregated message is no longer streaming
            )

            # Create new event based on the base event type
            aggregated_events = []
            if isinstance(base_event, PublishToTopicEvent):
                aggregated_events = [
                    PublishToTopicEvent(
                        topic_name=base_event.topic_name,
                        publisher_name=base_event.publisher_name,
                        publisher_type=base_event.publisher_type,
                        invoke_context=base_event.invoke_context,
                        offset=base_event.offset,
                        data=[aggregated_message],
                        consumed_events=getattr(base_event, "consumed_events", []),
                    )
                ]
            elif isinstance(base_event, ConsumeFromTopicEvent):
                aggregated_events = [
                    ConsumeFromTopicEvent(
                        topic_name=base_event.topic_name,
                        consumer_name=base_event.consumer_name,
                        consumer_type=base_event.consumer_type,
                        invoke_context=base_event.invoke_context,
                        offset=base_event.offset,
                        data=[aggregated_message],
                    )
                ]
            elif isinstance(base_event, OutputTopicEvent):
                aggregated_events = [
                    OutputTopicEvent(
                        topic_name=base_event.topic_name,
                        publisher_name=base_event.publisher_name,
                        publisher_type=base_event.publisher_type,
                        invoke_context=base_event.invoke_context,
                        offset=base_event.offset,
                        data=[aggregated_message],
                        consumed_events=getattr(base_event, "consumed_events", []),
                    )
                ]

            output_events.extend(aggregated_events)

    return output_events


def publish_events(
    node: Node,
    invoke_context: InvokeContext,
    result: Messages,
    consumed_events: List[ConsumeFromTopicEvent],
) -> List[PublishToTopicEvent | OutputTopicEvent]:
    published_events: List[PublishToTopicEvent | OutputTopicEvent] = []
    for topic in node.publish_to:
        event = topic.publish_data(
            invoke_context=invoke_context,
            publisher_name=node.name,
            publisher_type=node.type,
            data=result,
            consumed_events=consumed_events,
        )
        if event:
            published_events.append(event)

    all_events: List[TopicEvent] = []
    all_events.extend(consumed_events)
    all_events.extend(published_events)

    return all_events


async def a_publish_events(
    node: Node,
    result: Messages,
    invoke_context: InvokeContext,
    consumed_events: List[ConsumeFromTopicEvent],
) -> List[PublishToTopicEvent | OutputTopicEvent]:
    published_events: List[PublishToTopicEvent | OutputTopicEvent] = []
    for topic in node.publish_to:
        event = await topic.a_publish_data(
            data=result,
            invoke_context=invoke_context,
            publisher_name=node.name,
            publisher_type=node.type,
            consumed_events=consumed_events,
        )

        if event:
            published_events.append(event)

    return published_events


def get_node_input(node: Node) -> List[ConsumeFromTopicEvent]:
    consumed_events: List[ConsumeFromTopicEvent] = []

    node_subscribed_topics = node._subscribed_topics.values()

    # Process each topic the node is subscribed to
    for subscribed_topic in node_subscribed_topics:
        if subscribed_topic.can_consume(node.name):
            # Get messages from topic and create consume events
            node_consumed_events = subscribed_topic.consume(node.name)
            for event in node_consumed_events:
                consumed_event = ConsumeFromTopicEvent(
                    invoke_context=event.invoke_context,
                    topic_name=event.topic_name,
                    consumer_name=node.name,
                    consumer_type=node.type,
                    offset=event.offset,
                    data=event.data,
                )
                consumed_events.append(consumed_event)

    return consumed_events


async def a_get_node_input(
    node: Node,
) -> Tuple[List[ConsumeFromTopicEvent], List[ConsumeFromTopicEvent]]:
    consumed_events: List[ConsumeFromTopicEvent] = []
    ignored_events: List[ConsumeFromTopicEvent] = []

    node_subscribed_topics = node._subscribed_topics.values()

    # Process each topic the node is subscribed to
    for subscribed_topic in node_subscribed_topics:
        if subscribed_topic.can_consume(node.name):
            # Get messages from topic and create consume events
            node_consumed_events = await subscribed_topic.a_consume(node.name)
            for event in node_consumed_events:
                if isinstance(event, PublishToTopicEvent):
                    consumed_event = ConsumeFromTopicEvent(
                        invoke_context=event.invoke_context,
                        topic_name=event.topic_name,
                        consumer_name=node.name,
                        consumer_type=node.type,
                        offset=event.offset,
                        data=event.data,
                    )
                    consumed_events.append(consumed_event)
                else:
                    # Ignore output events, they are not needed for node input
                    ignored_events.append(
                        ConsumeFromTopicEvent(
                            invoke_context=event.invoke_context,
                            topic_name=event.topic_name,
                            consumer_name=node.name,
                            consumer_type=node.type,
                            offset=event.offset,
                            data=event.data,
                        )
                    )

    return consumed_events, ignored_events


# ──────────────────────────────────────────────────────────────────────────────
# 1.  Processing tracker – counts active consumer cycles
# ──────────────────────────────────────────────────────────────────────────────
class AsyncNodeTracker:
    def __init__(self) -> None:
        self._active: set[str] = set()
        self._processing_count: Dict[str, int] = defaultdict(
            int
        )  # Track how many times each node processed
        self._cond = asyncio.Condition()
        self._idle_event = asyncio.Event()
        # Set the event initially since we start in idle state
        self._idle_event.set()

    def reset(self) -> None:
        """
        Reset the tracker to its initial state.
        """
        self._active: set[str] = set()
        self._processing_count: Dict[str, int] = defaultdict(int)
        self._cond = asyncio.Condition()
        self._idle_event = asyncio.Event()
        # Set the event initially since we start in idle state
        self._idle_event.set()

    async def enter(self, node_name: str) -> None:
        async with self._cond:
            self._idle_event.clear()
            self._active.add(node_name)
            self._processing_count[node_name] += 1

    async def leave(self, node_name: str) -> None:
        async with self._cond:
            self._active.discard(node_name)
            if not self._active:
                self._idle_event.set()
                self._cond.notify_all()

    async def wait_idle_event(self) -> None:
        """
        Wait until the tracker is idle, meaning no active nodes.
        This is useful for synchronization points in workflows.
        """
        await self._idle_event.wait()

    def is_idle(self) -> bool:
        return not self._active

    def get_activity_count(self) -> int:
        """Get total processing count across all nodes"""
        return sum(self._processing_count.values())


async def output_listener(
    topic: TopicBase,
    queue: asyncio.Queue,
    consumer_name: str,
    tracker: AsyncNodeTracker,
):
    """
    Streams *matching* records from `topic` into `queue`.
    Exits when the graph is idle *and* the topic has no more unseen data,
    with proper handling for downstream node activation.
    """
    last_activity_count = 0

    while True:
        # waiter 1: "some records arrived"
        topic_task = asyncio.create_task(topic.a_consume(consumer_name))
        # waiter 2: "graph just became idle"
        idle_event_waiter = asyncio.create_task(tracker.wait_idle_event())

        done, pending = await asyncio.wait(
            {topic_task, idle_event_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # ---- If records arrived -----------------------------------------
        if topic_task in done:
            output_events = topic_task.result()

            for output_event in output_events:
                await queue.put(output_event)

        # ---- Check for workflow completion ----------------
        if idle_event_waiter in done and tracker.is_idle():
            current_activity = tracker.get_activity_count()

            # If no new activity since last check and no data, we're done
            if current_activity == last_activity_count and not topic.can_consume(
                consumer_name
            ):
                # cancel an unfinished waiter (if any) to avoid warnings
                for t in pending:
                    t.cancel()
                break

            last_activity_count = current_activity

        # Cancel the topic task since we're checking idle state
        for t in pending:
            t.cancel()


class MergeIdleQueue:

    def __init__(self, queue: asyncio.Queue, tracker: AsyncNodeTracker):
        self.queue = queue
        self.tracker = tracker

    def __aiter__(self):
        return self

    async def __anext__(self):
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
