"""Seeding and event-replay recovery for :meth:`WorkflowRun.init`.

For a fresh request (no prior events for the ``assistant_request_id``) this seeds
the input topics. Otherwise it restores topic state from the persisted events and
re-seeds the tracker with the work still pending consumption, so a resumed
parallel run drains the restored work instead of declaring immediate quiescence.

The run starts with empty queues and a fresh tracker, so -- unlike the old
definition-level ``init_workflow`` -- this performs no resets.
"""

from typing import TYPE_CHECKING
from typing import Dict
from typing import List
from typing import Set

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions import WorkflowError
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_types import TopicType

if TYPE_CHECKING:
    from grafi.workflows.impl.workflow_run import WorkflowRun


async def init_run(
    run: "WorkflowRun", input_data: PublishToTopicEvent, is_sequential: bool
) -> None:
    invoke_context = input_data.invoke_context

    events = [
        event
        for event in await run.event_store.get_agent_events(
            invoke_context.assistant_request_id
        )
        if isinstance(event, TopicEvent)
    ]

    if len(events) == 0:
        await _seed_fresh(run, input_data, is_sequential)
    else:
        await _restore(run, input_data, events, is_sequential)


async def _seed_fresh(
    run: "WorkflowRun", input_data: PublishToTopicEvent, is_sequential: bool
) -> None:
    """Publish the input to each agent-input topic for a brand-new request."""
    input_topics: List[TopicBase] = [
        topic
        for topic in run.topics.values()
        if topic.type == TopicType.AGENT_INPUT_TOPIC_TYPE
    ]

    events_to_record: List[TopicEvent] = []
    # One delivery per consumer of each seeded input topic (not one per topic),
    # so a fan-out input feeding several nodes is not declared quiescent after
    # only the first node commits.
    seeded_delivery_count = 0
    for input_topic in input_topics:
        event = await input_topic.publish_data(
            input_data.model_copy(
                update={
                    "publisher_name": run.name,
                    "publisher_type": run.type,
                },
                deep=True,
            )
        )
        if event:
            events_to_record.append(event)
            seeded_delivery_count += len(run._topic_consumers(event.name))
            if is_sequential:
                await run._add_to_invoke_queue(event)

    if events_to_record:
        if not is_sequential and seeded_delivery_count:
            await run.tracker.on_messages_published(
                seeded_delivery_count, source="init_workflow"
            )
        await run.event_store.record_events(events_to_record)


async def _restore(
    run: "WorkflowRun",
    input_data: PublishToTopicEvent,
    events: List[TopicEvent],
    is_sequential: bool,
) -> None:
    """Restore publications by topic offset, then committed consumer cursors."""
    publications = sorted(
        (event for event in events if isinstance(event, PublishToTopicEvent)),
        key=lambda event: (event.name, event.offset),
    )
    # Store timestamps/insertion order need not match a topic's queue order.
    # Validate the entire snapshot before queue.put() could renumber anything.
    next_offsets: Dict[str, int] = {}
    for event in publications:
        expected = next_offsets.get(event.name, 0)
        if event.offset != expected:
            raise WorkflowError(
                message=(
                    f"Topic {event.name!r} history has missing or conflicting offsets: "
                    f"expected offset {expected}, found {event.offset}"
                ),
                invoke_context=input_data.invoke_context,
            )
        next_offsets[event.name] = expected + 1
    consumptions = [
        event for event in events if isinstance(event, ConsumeFromTopicEvent)
    ]
    for event in consumptions:
        if not 0 <= event.offset < next_offsets.get(event.name, 0):
            raise WorkflowError(
                message=f"Topic {event.name!r} history has no publication at consumed offset {event.offset}",
                invoke_context=input_data.invoke_context,
            )

    for publication in publications:
        await run.topics[publication.name].restore_topic(publication)
    for consumption in consumptions:
        await run.topics[consumption.name].restore_topic(consumption)
    if is_sequential:
        for node in run.nodes.values():
            if await run._node_can_invoke(node):
                run.invoke_queue.append(node)

    # Re-seed the tracker with messages still pending consumption so the resumed
    # parallel run drains restored work instead of declaring immediate quiescence.
    if not is_sequential:
        pending = await run._count_pending_consumable()
        if pending:
            await run.tracker.on_messages_published(pending, source="recovery_restore")

    await _reissue_paired_inputs(run, input_data, events, is_sequential)


async def _reissue_paired_inputs(
    run: "WorkflowRun",
    input_data: PublishToTopicEvent,
    events: List[TopicEvent],
    is_sequential: bool,
) -> None:
    """Re-issue paired in-workflow inputs for any consumed in-workflow output
    (e.g. a human-in-the-loop response resuming the flow)."""
    consumed_event_ids = input_data.consumed_event_ids
    consumed_events = [
        event for event in events if event.event_id in consumed_event_ids
    ]
    in_workflow_output_topic_names: Set[str] = set(
        event.name
        for event in consumed_events
        if event.type == TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE
    )

    for in_workflow_output_topic_name in in_workflow_output_topic_names:
        in_workflow_output_topic = run.topics.get(in_workflow_output_topic_name)
        if not (
            in_workflow_output_topic
            and isinstance(in_workflow_output_topic, InWorkflowOutputTopic)
        ):
            continue

        for (
            paired_in_workflow_input_topic_name
        ) in in_workflow_output_topic.paired_in_workflow_input_topic_names:
            paired_in_workflow_input_topic = run.topics.get(
                paired_in_workflow_input_topic_name
            )
            if not (
                paired_in_workflow_input_topic
                and isinstance(paired_in_workflow_input_topic, InWorkflowInputTopic)
            ):
                continue

            paired_event = await paired_in_workflow_input_topic.publish_data(
                input_data.model_copy(
                    update={
                        "publisher_name": run.name,
                        "publisher_type": run.type,
                    },
                    deep=True,
                )
            )
            if not paired_event:
                continue

            if not is_sequential:
                delivery_count = len(
                    run._topic_consumers(paired_in_workflow_input_topic_name)
                )
                if delivery_count:
                    await run.tracker.on_messages_published(
                        delivery_count, source="restore_paired_input"
                    )
            if is_sequential:
                await run._add_to_invoke_queue(paired_event)
            await run.event_store.record_event(paired_event)
