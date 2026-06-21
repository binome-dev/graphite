"""Sequential execution engine for a :class:`WorkflowRun`.

Drains the run's ready-queue one node at a time (concurrency = 1): consume the
node's inputs, invoke it, publish, enqueue any newly-ready nodes, and persist the
consumed + published events. Output is collected once the queue empties.
"""

from typing import TYPE_CHECKING
from typing import AsyncGenerator
from typing import List

from loguru import logger

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.workflows.impl.utils import get_node_input
from grafi.workflows.impl.utils import publish_events

if TYPE_CHECKING:
    from grafi.workflows.impl.workflow_run import WorkflowRun


async def invoke_sequential(
    run: "WorkflowRun", input_data: PublishToTopicEvent
) -> AsyncGenerator[ConsumeFromTopicEvent, None]:
    invoke_context = input_data.invoke_context
    consumed_events: List[ConsumeFromTopicEvent] = []
    try:
        while run.invoke_queue:
            if run._stop_requested:
                logger.info("Workflow execution stopped by assistant request")
                break

            node = run.invoke_queue.popleft()
            node_consumed_events: List[ConsumeFromTopicEvent] = await get_node_input(
                node, run.topics
            )

            if node_consumed_events:
                try:
                    published_events: List[PublishToTopicEvent] = []
                    async for result in node.invoke(
                        invoke_context, node_consumed_events
                    ):
                        published_events.extend(
                            await publish_events(
                                node,
                                result,
                                run.tracker,
                                run._topic_consumers,
                                run.topics,
                            )
                        )

                    for event in published_events:
                        await run._add_to_invoke_queue(event)

                    events: List[TopicEvent] = []
                    events.extend(node_consumed_events)
                    events.extend(published_events)

                    await run.event_store.record_events(events)
                except Exception as e:
                    raise NodeExecutionError(
                        node_name=node.name,
                        message=f"Node execution failed: {e}",
                        invoke_context=invoke_context,
                        cause=e,
                    ) from e

        consumed_events = await run._get_output_events()
        for event in consumed_events:
            yield event
    finally:
        if consumed_events:
            await run.event_store.record_events(consumed_events)
