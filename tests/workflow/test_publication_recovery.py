"""Canonical publication IDs and offsets survive both workflow engines."""

import asyncio
from typing import Any
from typing import Sequence

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.event import Event
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import NodeExecutionError
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
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.impl.parallel_engine import invoke_parallel
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
    acknowledged_tail = [
        record
        for record in await event_store.get_agent_events("r")
        if isinstance(record, ConsumeFromTopicEvent) and record.offset == 3
    ]
    assert sorted(record.name for record in acknowledged_tail) == [
        "output_a",
        "output_b",
    ]
    assert [
        record.model_dump()
        for record in (await event_store.get_events())[: len(stored)]
    ] == stored


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_readiness_uses_completed_recovery_snapshot(
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
    if sequential:
        assert list(recovered.invoke_queue) == []
    else:
        assert (await recovered.tracker.get_metrics())["uncommitted_messages"] == 1
    assert await recovered.topics["input_a"].consume("stream", timeout=0) == []
    assert len(await recovered.topics["input_b"].consume("stream", timeout=0)) == 1
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
@pytest.mark.parametrize("termination", ["failure", "stop", "close", "cancel"])
async def test_unpersisted_stream_output_is_replayed_after_interruption(
    event_store: EventStore, monkeypatch: pytest.MonkeyPatch, termination: str
) -> None:
    tool = StreamTool()
    release = asyncio.Event()

    async def invoke(
        self: StreamTool, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.calls += 1
        for text in ("one", "two", "three"):
            yield [Message(role="assistant", content=text, is_streaming=True)]
            if self.calls == 1 and text == "two":
                await release.wait()
                raise RuntimeError("stream interrupted")

    monkeypatch.setattr(StreamTool, "invoke", invoke)
    input_topic, output_topic = InputTopic(name="input"), OutputTopic(name="out")
    node = Node(
        name="stream",
        tool=tool,
        subscribed_expressions=[TopicExpr(topic=input_topic)],
        publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
    )
    workflow = EventDrivenWorkflow.builder().node(node).build()
    _, _, event = workflow_and_input()
    run = WorkflowRun(workflow, event_store)
    await run.init(event, is_sequential=False)
    engine = invoke_parallel(run, event)
    try:
        async with asyncio.timeout(3):
            assert (await anext(engine)).data[0].content == "one"
            assert (await anext(engine)).data[0].content == "two"
            if termination == "failure":
                release.set()
                with pytest.raises(NodeExecutionError, match="stream interrupted"):
                    await anext(engine)
            elif termination == "stop":
                run.stop()
                with pytest.raises(StopAsyncIteration):
                    await anext(engine)
            elif termination == "close":
                await engine.aclose()
            else:
                # Cancellation injected at a streamed yield still runs the
                # engine's acknowledgment and node-task cleanup path.
                with pytest.raises(asyncio.CancelledError):
                    await engine.athrow(asyncio.CancelledError())
    finally:
        await engine.aclose()
    history = await event_store.get_agent_events("r")
    assert not any(
        isinstance(record, ConsumeFromTopicEvent) and record.name == "out"
        for record in history
    ), "A streamed output cannot be acknowledged before its publication is persisted"
    async with asyncio.timeout(3):
        retried = [
            output
            async for output in WorkflowRun(workflow, event_store).run(event, False)
        ]
    assert [output.data[0].content for output in retried] == ["one", "two", "three"]
    assert tool.calls == 2


@pytest.mark.asyncio
async def test_fanin_gap_from_failed_producer_is_reported_on_recovery(
    event_store: EventStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a_enqueued, b_stored, sink_consumed = (asyncio.Event() for _ in range(3))
    original_record = event_store.record_events

    async def record(events: Sequence[Event]) -> None:
        await original_record(events)
        for event in events:
            if (
                isinstance(event, PublishToTopicEvent)
                and event.name == "mid"
                and event.publisher_name == "b"
            ):
                b_stored.set()
            if (
                isinstance(event, ConsumeFromTopicEvent)
                and event.name == "mid"
                and event.offset == 0
            ):
                sink_consumed.set()

    async def invoke(
        self: StreamTool, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        if self.name == "a":
            yield [Message(role="assistant", content="a")]
            a_enqueued.set()
            await b_stored.wait()
            await sink_consumed.wait()
            raise RuntimeError("producer a failed")
        if self.name == "b":
            await a_enqueued.wait()
        yield [Message(role="assistant", content=self.name)]

    monkeypatch.setattr(event_store, "record_events", record)
    monkeypatch.setattr(StreamTool, "invoke", invoke)
    input_topic, mid, out = (
        InputTopic(name="input"),
        Topic(name="mid"),
        OutputTopic(name="out"),
    )

    def node(name: str, subscription: TopicExpr, destination: TopicBase) -> Node:
        return Node(
            name=name,
            tool=StreamTool(name=name),
            subscribed_expressions=[subscription],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=destination)]),
        )

    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("a", TopicExpr(topic=input_topic), mid))
        .node(node("b", TopicExpr(topic=input_topic), mid))
        .node(node("sink", TopicExpr(topic=mid), out))
        .build()
    )
    _, _, event = workflow_and_input()
    async with asyncio.timeout(3):
        with pytest.raises(NodeExecutionError, match="producer a failed"):
            async for _ in workflow.invoke(event):
                pass
    history = await event_store.get_agent_events("r")
    assert [
        event.offset
        for event in history
        if isinstance(event, PublishToTopicEvent) and event.name == "mid"
    ] == [1]
    assert any(
        isinstance(event, ConsumeFromTopicEvent)
        and event.name == "mid"
        and event.offset == 0
        for event in history
    )
    with pytest.raises(WorkflowError, match="expected offset 0, found 1"):
        await WorkflowRun(workflow, event_store).init(event, False)


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


@pytest.mark.asyncio
async def test_sequential_recovery_queues_ready_nodes_in_definition_order(
    event_store: EventStore,
) -> None:
    _, _, event = workflow_and_input()
    first, second = InputTopic(name="z_first"), InputTopic(name="a_second")
    output = OutputTopic(name="out")
    workflow = EventDrivenWorkflow.builder()
    for name, topic in (("first", first), ("second", second)):
        workflow.node(
            Node(
                name=name,
                tool=StreamTool(),
                subscribed_expressions=[TopicExpr(topic=topic)],
                publisher_router=PublisherRouter(routes=[PublishRoute(topic=output)]),
            )
        )
    definition = workflow.build()
    await event_store.record_events(
        [
            event.model_copy(
                update={"event_id": "second", "name": second.name, "offset": 0}
            ),
            event.model_copy(
                update={"event_id": "first", "name": first.name, "offset": 0}
            ),
        ]
    )
    run = WorkflowRun(definition, event_store)
    await run.init(event, is_sequential=True)
    assert [node.name for node in run.invoke_queue] == ["first", "second"]
