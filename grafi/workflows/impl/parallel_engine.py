"""Parallel execution engine for a :class:`WorkflowRun`.

Runs one ``asyncio.Task`` per node and multiplexes the output topics through an
:class:`~grafi.workflows.impl.async_output_queue.AsyncOutputQueue`, terminating
on tracker quiescence (or the no-progress backstop). ``_invoke_node`` is the
per-node loop: wait for a satisfying set of inputs, consume, invoke, publish,
commit, and persist.
"""

import asyncio
from typing import TYPE_CHECKING
from typing import AsyncGenerator
from typing import Dict
from typing import List
from typing import Tuple

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.models.invoke_context import InvokeContext
from grafi.nodes.node_base import NodeBase
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.async_output_queue import AsyncOutputQueue
from grafi.workflows.impl.utils import publish_events

if TYPE_CHECKING:
    from grafi.workflows.impl.workflow_run import WorkflowRun


async def invoke_parallel(
    run: "WorkflowRun", input_data: PublishToTopicEvent
) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
    invoke_context = input_data.invoke_context

    node_processing_task = [
        asyncio.create_task(
            _invoke_node(run, invoke_context=invoke_context, node=node),
            name=node.name,
        )
        for node in run.nodes.values()
    ]

    output_topics: List[TopicBase] = [
        topic
        for topic in run.topics.values()
        if topic.type == TopicType.AGENT_OUTPUT_TOPIC_TYPE
        or topic.type == TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE
    ]

    output_queue = AsyncOutputQueue(
        output_topics,
        run.name,
        run.tracker,
        progress_possible=run._progress_possible,
    )
    await output_queue.start_listeners()

    consumed_output_events: List[ConsumeFromTopicEvent] = []
    try:
        async for event in output_queue:
            for i, task in enumerate(node_processing_task):
                if task.done() and not task.cancelled():
                    try:
                        task.result()
                    except Exception as task_error:
                        node_name = (
                            list(run.nodes.keys())[i]
                            if i < len(run.nodes)
                            else f"node_{i}"
                        )
                        for t in node_processing_task:
                            if not t.done():
                                t.cancel()
                        run.stop()
                        # The lifecycle decorator already reported this failure;
                        # do not log again, and do not re-wrap an existing
                        # NodeExecutionError for the same node.
                        if isinstance(task_error, NodeExecutionError):
                            raise task_error
                        raise NodeExecutionError(
                            node_name=node_name,
                            message="Node execution failed",
                            invoke_context=invoke_context,
                            cause=task_error,
                        ) from task_error

            consumed_event = ConsumeFromTopicEvent(
                name=event.name,
                type=event.type,
                consumer_name=run.name,
                consumer_type=run.type,
                invoke_context=event.invoke_context,
                offset=event.offset,
                data=event.data,
            )
            yield consumed_event
            consumed_output_events.append(consumed_event)
    finally:
        await output_queue.stop_listeners()

        # A node may fail, stop or be cancelled after yielding chunks but before
        # persisting its publications. Leave those outputs unacknowledged so a
        # fresh run can replay the input and deliver the complete stream again.
        persisted_outputs = [
            event
            for event in consumed_output_events
            if (event.name, event.offset) in run._persisted_publications
        ]
        await run._commit_events(
            consumer_name=run.name,
            topic_events=persisted_outputs,
            track_commit=False,
        )

        run.stop()

        if persisted_outputs:
            await run.event_store.record_events(persisted_outputs)

        for t in node_processing_task:
            t.cancel()
        node_results = await asyncio.gather(
            *node_processing_task, return_exceptions=True
        )

        for i, result in enumerate(node_results):
            if isinstance(result, Exception) and not isinstance(
                result, asyncio.CancelledError
            ):
                if isinstance(result, NodeExecutionError):
                    raise result
                node_name = (
                    list(run.nodes.keys())[i] if i < len(run.nodes) else f"node_{i}"
                )
                raise NodeExecutionError(
                    node_name=node_name,
                    message="Node execution failed",
                    invoke_context=invoke_context,
                    cause=result,
                ) from result


async def _invoke_node(
    run: "WorkflowRun", invoke_context: InvokeContext, node: NodeBase
) -> None:
    """Node invocation loop for the parallel engine."""
    buffer: Dict[str, List[TopicEvent]] = {}
    active_tasks: List[asyncio.Task[Tuple[str, List[TopicEvent]]]] = []

    async def _read_topic(
        consumer_name: str, topic: TopicBase
    ) -> Tuple[str, List[TopicEvent]]:
        try:
            return topic.name, await topic.consume(consumer_name)
        except asyncio.CancelledError as error:
            task = asyncio.current_task()
            if task is not None and task.cancelling() == 0:
                raise RuntimeError("Topic read was unexpectedly cancelled") from error
            raise

    async def wait_node_invoke(node: NodeBase) -> None:
        while not node.can_invoke_with_topics(list(buffer.keys())):
            if run._stop_requested:
                return
            # Wait on this run's copy of each subscribed topic.
            tasks = [
                asyncio.create_task(_read_topic(node.name, run.topics[topic.name]))
                for topic in node.subscribed_topics
            ]
            active_tasks.extend(tasks)
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            # A completed read may already have advanced its cursor. Keep the
            # node active during sibling cleanup so that slow cancellation
            # cannot make the output loop mistake this work for parked inputs.
            await run.tracker.hold(node.name)
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                await run.tracker.leave(node.name)
            active_tasks.clear()
            # Abort on the first failure without acknowledging this batch; a
            # fresh run restores uncommitted publications from the store.
            for result in results:
                if isinstance(result, asyncio.CancelledError):
                    continue  # _read_topic wraps transport-raised cancellation.
                if isinstance(result, Exception):
                    raise result
                if isinstance(result, BaseException):
                    raise RuntimeError("Topic read failed") from result
                topic_name, recs = result
                if recs:
                    buffer.setdefault(topic_name, []).extend(recs)

    async def _cancel_all_active_tasks() -> None:
        for task in active_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*active_tasks, return_exceptions=True)
        active_tasks.clear()

    try:
        while not run._stop_requested:
            await wait_node_invoke(node)

            if run._stop_requested:
                break

            await run.tracker.enter(node.name)
            try:
                consumed_events: List[ConsumeFromTopicEvent] = []
                for events in buffer.values():
                    for event in events:
                        consumed_events.append(
                            ConsumeFromTopicEvent(
                                invoke_context=event.invoke_context,
                                name=event.name,
                                type=event.type,
                                consumer_name=node.name,
                                consumer_type=node.type,
                                offset=event.offset,
                                data=event.data,
                            )
                        )

                node_output_events: List[PublishToTopicEvent] = []
                if consumed_events:
                    async for event in node.invoke(invoke_context, consumed_events):
                        node_output_events.extend(
                            await publish_events(
                                node=node,
                                publish_event=event,
                                tracker=run.tracker,
                                consumers_of=run._topic_consumers,
                                topics=run.topics,
                            )
                        )

                await run._commit_events(
                    consumer_name=node.name, topic_events=consumed_events
                )
                await run.event_store.record_events(
                    [*consumed_events, *node_output_events]
                )
                run._persisted_publications.update(
                    (event.name, event.offset) for event in node_output_events
                )
            finally:
                await run.tracker.leave(node.name)
                buffer.clear()
    except Exception as e:
        # Signal once on the owning loop, without a cancellation point that
        # could replace the node/read failure before it reaches the caller.
        run.tracker.force_stop_sync()
        if isinstance(e, NodeExecutionError):
            raise
        raise NodeExecutionError(
            node_name=node.name,
            message="Node execution failed",
            invoke_context=invoke_context,
            cause=e,
        ) from e
    finally:
        await _cancel_all_active_tasks()
        buffer.clear()
