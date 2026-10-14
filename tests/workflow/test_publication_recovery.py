"""Canonical publication IDs and offsets survive both workflow engines."""

import asyncio
from typing import Any

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import WorkflowError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.tools.tool import Tool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.impl.utils import get_async_output_events
from grafi.workflows.impl.utils import publish_events
from grafi.workflows.impl.workflow_run import WorkflowRun


class StreamTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    calls: int = 0
    inputs: list[list[str]] = Field(default_factory=list)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.calls += 1
        self.inputs.append([str(message.content) for message in input_data])
        for text in ("one", "two", "three"):
            yield [Message(role="assistant", content=text, is_streaming=True)]

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "StreamTool":
        return cls()


def workflow_and_input() -> tuple[EventDrivenWorkflow, StreamTool, PublishToTopicEvent]:
    a, b = InputTopic(name="input_a"), InputTopic(name="input_b")
    x, y = OutputTopic(name="output_a"), OutputTopic(name="output_b")
    tool = StreamTool()
    node = Node(
        name="stream",
        tool=tool,
        subscribed_expressions=[
            SubscriptionBuilder().subscribed_to(a).and_().subscribed_to(b).build()
        ],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=x), PublishRoute(topic=y), PublishRoute(topic=x)]
        ),
    )
    workflow = EventDrivenWorkflow.builder().node(node).build()
    event = PublishToTopicEvent(
        invoke_context=InvokeContext(
            conversation_id="c", invoke_id="i", assistant_request_id="r"
        ),
        data=[Message(role="user", content="seed")],
    )
    return workflow, tool, event


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_fanout_stream_history_and_same_request_recovery(
    event_store: EventStore, sequential: bool
) -> None:
    workflow, tool, event = workflow_and_input()
    async with asyncio.timeout(5):
        outputs = [output async for output in workflow.invoke(event, sequential)]
    assert len(outputs) == 6
    assert tool.calls == 1 and tool.inputs == [["seed", "seed"]]
    history = await event_store.get_agent_events("r")
    seeds = [
        record
        for record in history
        if isinstance(record, PublishToTopicEvent) and record.name.startswith("input_")
    ]
    assert len(seeds) == 2
    assert seeds[0].event_id != seeds[1].event_id
    assert all(seed.emission_id == event.event_id for seed in seeds)
    publications = [
        record
        for record in history
        if isinstance(record, PublishToTopicEvent) and record.name.startswith("output_")
    ]
    assert len(publications) == len({record.event_id for record in publications}) == 6
    for name in ("output_a", "output_b"):
        chunks = [record for record in publications if record.name == name]
        consumes = [
            record
            for record in history
            if isinstance(record, ConsumeFromTopicEvent)
            and record.name == name
            and record.consumer_name == workflow.name
        ]
        assert [record.offset for record in chunks] == [0, 1, 2]
        assert [record.offset for record in consumes] == [0, 1, 2]
        assert [record.data[0].content for record in chunks] == ["one", "two", "three"]
        assert all(record.data[0].is_streaming for record in chunks + consumes)
    for offset in range(3):
        pair = [record for record in publications if record.offset == offset]
        assert pair[0].emission_id == pair[1].emission_id

    # Display aggregation remains explicit and must not rewrite raw history.
    snapshots = [output.model_dump() for output in outputs]
    assert [record.data[0].content for record in get_async_output_events(outputs)] == [
        "onetwothree",
        "onetwothree",
    ]
    assert [output.model_dump() for output in outputs] == snapshots

    # Put canonical history in reverse read order, then add a later publication
    # at each destination. Consumption through 2 must not skip publication 3.
    later = [
        PublishToTopicEvent(
            name=name,
            type=workflow._topics[name].type,
            offset=3,
            invoke_context=event.invoke_context,
            data=[Message(role="assistant", content="later")],
        )
        for name in ("output_a", "output_b")
    ]
    await event_store.clear_events()
    await event_store.record_events([*later, *reversed(history)])
    stored = [record.model_dump() for record in await event_store.get_events()]
    async with asyncio.timeout(5):
        recovered = [output async for output in workflow.invoke(event, sequential)]
    assert sorted(
        (output.name, output.offset, output.data[0].content) for output in recovered
    ) == [("output_a", 3, "later"), ("output_b", 3, "later")]
    assert tool.calls == 1, "Recovery reran committed upstream work"
    assert [
        record.model_dump()
        for record in (await event_store.get_events())[: len(stored)]
    ] == stored


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_sequential_readiness_uses_completed_recovery_snapshot(
    event_store: EventStore, sequential: bool
) -> None:
    workflow, _, event = workflow_and_input()
    run = WorkflowRun(workflow, event_store)
    await run.init(event, sequential)
    publications = await event_store.get_agent_events("r")
    # Only A was consumed. An AND join with remaining B must stay parked.
    consumed = ConsumeFromTopicEvent(
        name="input_a",
        type=workflow._topics["input_a"].type,
        offset=0,
        consumer_name="stream",
        consumer_type="Node",
        invoke_context=event.invoke_context,
        data=event.data,
    )
    await event_store.record_event(consumed)
    recovered = WorkflowRun(workflow, event_store)
    await recovered.init(event, sequential)
    assert await recovered.topics["input_a"].consume("stream", timeout=0) == []
    assert len(await recovered.topics["input_b"].consume("stream", timeout=0)) == 1
    assert list(recovered.invoke_queue) == []
    assert len(publications) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("offsets", [[0, 2], [0, 0]])
async def test_incomplete_or_conflicting_history_is_not_renumbered(
    event_store: EventStore, offsets: list[int]
) -> None:
    workflow, _, event = workflow_and_input()
    records = [
        PublishToTopicEvent(
            name="input_a",
            type=workflow._topics["input_a"].type,
            offset=offset,
            invoke_context=event.invoke_context,
            data=event.data,
        )
        for offset in offsets
    ]
    await event_store.record_events(records)
    snapshot = [record.model_dump() for record in records]
    run = WorkflowRun(workflow, event_store)
    with pytest.raises(WorkflowError, match="history.*offset"):
        await run.init(event, is_sequential=False)
    assert [record.model_dump() for record in records] == snapshot
    assert await run.topics["input_a"].consume("stream", timeout=0) == []


@pytest.mark.asyncio
async def test_duplicate_routes_register_one_delivery_per_destination() -> None:
    workflow, _, event = workflow_and_input()
    run = WorkflowRun(workflow)
    tracker = AsyncNodeTracker()
    publications = await publish_events(
        run.nodes["stream"], event, tracker, run._topic_consumers, run.topics
    )
    assert [publication.name for publication in publications] == [
        "output_a",
        "output_b",
    ]
    assert (await tracker.get_metrics())["uncommitted_messages"] == 2
    assert await run.topics["output_a"].unconsumed_count(run.name) == 1
    assert await run.topics["output_b"].unconsumed_count(run.name) == 1


@pytest.mark.asyncio
async def test_consumption_past_surviving_history_is_not_silently_replayed(
    event_store: EventStore,
) -> None:
    workflow, _, event = workflow_and_input()
    publication = event.model_copy(update={"name": "input_a", "offset": 0})
    consumption = ConsumeFromTopicEvent(
        name="input_a",
        offset=2,
        consumer_name="stream",
        consumer_type="Node",
        invoke_context=event.invoke_context,
        data=event.data,
    )
    await event_store.record_events([publication, consumption])
    run = WorkflowRun(workflow, event_store)
    with pytest.raises(WorkflowError, match="history.*consumed offset 2"):
        await run.init(event, is_sequential=False)
    assert await run.topics["input_a"].consume("stream", timeout=0) == []
