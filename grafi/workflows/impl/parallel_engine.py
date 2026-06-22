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
from grafi.workflows.impl.utils import get_async_output_events
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

        await run._commit_events(
            consumer_name=run.name,
            topic_events=consumed_output_events,
            track_commit=False,
        )

        run.stop()

        if consumed_output_events:
            await run.event_store.record_events(
                get_async_output_events(consumed_output_events)
            )

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
    active_tasks: List[asyncio.Task] = []

    async def _wait_and_buffer(consumer_name: str, topic: TopicBase) -> None:
        recs = await topic.consume(consumer_name)
        if topic.name not in buffer:
            buffer[topic.name] = []
        buffer[topic.name].extend(recs)

    async def _ignore_cancel(task: asyncio.Task) -> None:
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def wait_node_invoke(node: NodeBase) -> None:
        while not node.can_invoke_with_topics(list(buffer.keys())):
            if run._stop_requested:
                return
            # Wait on this run's copy of each subscribed topic.
            tasks = [
                asyncio.create_task(_wait_and_buffer(node.name, run.topics[topic.name]))
                for topic in node.subscribed_topics
            ]
            active_tasks.extend(tasks)
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
                asyncio.create_task(_ignore_cancel(t))
            active_tasks[:] = [t for t in active_tasks if not t.done()]

    def _cancel_all_active_tasks() -> None:
        for task in active_tasks:
            if not task.done():
                task.cancel()
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
                await run.event_store.record_events(consumed_events)
                await run.event_store.record_events(
                    get_async_output_events(node_output_events)
                )
            except Exception as node_error:
                await run.tracker.force_stop()
                if isinstance(node_error, NodeExecutionError):
                    raise
                raise NodeExecutionError(
                    node_name=node.name,
                    message="Node execution failed",
                    invoke_context=invoke_context,
                    cause=node_error,
                ) from node_error
            finally:
                await run.tracker.leave(node.name)
                buffer.clear()
    except asyncio.CancelledError:
        # Cancellation is normal shutdown, not a failure -- do not log/report it.
        _cancel_all_active_tasks()
        raise
    except NodeExecutionError:
        _cancel_all_active_tasks()
        raise
    except Exception as e:
        _cancel_all_active_tasks()
        raise NodeExecutionError(
            node_name=node.name,
            message="Node execution failed",
            invoke_context=invoke_context,
            cause=e,
        ) from e
    finally:
        _cancel_all_active_tasks()
        buffer.clear()
