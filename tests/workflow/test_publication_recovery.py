"""Canonical publication IDs and offsets survive parallel and sequential runs."""

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
from grafi.common.events.topic_events.topic_event import TopicEvent
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
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.impl.utils import get_async_output_events


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


async def topic_history(event_store: EventStore) -> list[TopicEvent]:
    """The request's stored publications and consumptions."""
    return [
        record
        for record in await event_store.get_agent_events("r")
        if isinstance(record, TopicEvent)
    ]


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
    workflow, tool, event = workflow_and_input()
    seeds = [
        event.model_copy(
            update={
                "event_id": f"seed-{name}",
                "name": name,
                "type": workflow._topics[name].type,
                "offset": 0,
            }
        )
        for name in ("input_a", "input_b")
    ]
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
    await event_store.record_events([*seeds, consumed])
    async with asyncio.timeout(5):
        outputs = [output async for output in workflow.invoke(event, sequential)]
    assert outputs == [] and tool.calls == 0
    # Resuming published no new input either.
    assert len(await topic_history(event_store)) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("offsets", [[0, 2], [0, 0]])
async def test_incomplete_or_conflicting_history_is_not_renumbered(
    event_store: EventStore, offsets: list[int]
) -> None:
    workflow, tool, event = workflow_and_input()
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
    with pytest.raises(WorkflowError, match="history.*offset"):
        async with asyncio.timeout(5):
            async for _ in workflow.invoke(event):
                pass
    assert [record.model_dump() for record in records] == snapshot
    assert len(await topic_history(event_store)) == len(records)
    assert tool.calls == 0


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
    engine = workflow.invoke(event)
    try:
        async with asyncio.timeout(3):
            assert (await anext(engine)).data[0].content == "one"
            assert (await anext(engine)).data[0].content == "two"
            if termination == "failure":
                release.set()
                with pytest.raises(NodeExecutionError, match="stream interrupted"):
                    await anext(engine)
            elif termination == "stop":
                workflow.stop()
                with pytest.raises(StopAsyncIteration):
                    await anext(engine)
            elif termination == "close":
                await engine.aclose()
            else:
                # Cancellation injected at a streamed yield still stops the
                # step and runs the acknowledgement path.
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
        retried = [output async for output in workflow.invoke(event)]
    assert [output.data[0].content for output in retried] == ["one", "two", "three"]
    assert tool.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("fan_in", [False, True], ids=["pipeline", "fan-in"])
async def test_failed_producer_never_exposes_internal_publications(
    event_store: EventStore,
    monkeypatch: pytest.MonkeyPatch,
    fan_in: bool,
) -> None:
    a_emitted, b_stored = asyncio.Event(), asyncio.Event()
    original_record = event_store.record_events

    async def record(events: Sequence[Event]) -> None:
        await original_record(events)
        if any(
            isinstance(event, PublishToTopicEvent) and event.publisher_name == "b"
            for event in events
        ):
            b_stored.set()

    async def invoke(
        self: StreamTool, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.calls += 1
        self.inputs.append([str(message.content) for message in input_data])
        if self.name == "a":
            yield [Message(role="assistant", content="a")]
            a_emitted.set()
            if self.calls == 1:
                if fan_in:
                    await b_stored.wait()
                raise RuntimeError("producer a failed")
            return
        if self.name == "b":
            await a_emitted.wait()
            yield [Message(role="assistant", content="b")]
            return
        yield [Message(role="assistant", content="|".join(self.inputs[-1]))]

    monkeypatch.setattr(event_store, "record_events", record)
    monkeypatch.setattr(StreamTool, "invoke", invoke)
    input_topic, mid, out = (
        InputTopic(name="input"),
        Topic(name="mid"),
        OutputTopic(name="out"),
    )
    tools: dict[str, StreamTool] = {}

    def node(name: str, subscription: TopicExpr, destination: TopicBase) -> Node:
        tools[name] = StreamTool(name=name)
        return Node(
            name=name,
            tool=tools[name],
            subscribed_expressions=[subscription],
            publisher_router=PublisherRouter(routes=[PublishRoute(topic=destination)]),
        )

    builder = (
        EventDrivenWorkflow.builder()
        .node(node("a", TopicExpr(topic=input_topic), mid))
        .node(node("sink", TopicExpr(topic=mid), out))
    )
    if fan_in:
        builder.node(node("b", TopicExpr(topic=input_topic), mid))
    workflow = builder.build()
    _, _, event = workflow_and_input()
    first_run: list[str] = []
    async with asyncio.timeout(3):
        with pytest.raises(NodeExecutionError, match="producer a failed"):
            async for output in workflow.invoke(event):
                first_run.extend(str(output.data[0].content).split("|"))

    # The failed step's chunk was never visible to the downstream node, and the
    # stored topic positions have no gap that recovery would have to reject.
    assert ["a"] not in tools["sink"].inputs
    history = await event_store.get_agent_events("r")
    stored_mid = [
        (record.offset, record.data[0].content)
        for record in history
        if isinstance(record, PublishToTopicEvent) and record.name == "mid"
    ]
    assert stored_mid == ([(0, "b")] if fan_in else [])

    async with asyncio.timeout(3):
        outputs = [output async for output in workflow.invoke(event)]
    assert tools["a"].calls == 2
    # Each input reaches the sink's output once; B's output may be redelivered
    # because the first run can fail before the caller acknowledges it.
    delivered = [
        part for output in outputs for part in str(output.data[0].content).split("|")
    ]
    assert delivered.count("a") == 1
    # Nothing is lost across both runs; B's output may repeat (at least once).
    assert set(first_run + delivered) == ({"a", "b"} if fan_in else {"a"})
    history = await event_store.get_agent_events("r")
    offsets = [
        record.offset
        for record in history
        if isinstance(record, PublishToTopicEvent) and record.name == "mid"
    ]
    assert sorted(offsets) == list(range(len(offsets)))


@pytest.mark.asyncio
async def test_node_persistence_failure_keeps_inputs_unacknowledged_for_retry(
    event_store: EventStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow, tool, event = workflow_and_input()
    original_record = event_store.record_events
    failed_batches: list[list[Event]] = []
    failure = OSError("step persistence failed")

    async def record(events: Sequence[Event]) -> None:
        if not failed_batches and any(
            isinstance(record, PublishToTopicEvent) and record.name == "output_a"
            for record in events
        ):
            failed_batches.append(list(events))
            raise failure
        await original_record(events)

    monkeypatch.setattr(event_store, "record_events", record)
    async with asyncio.timeout(3):
        # A failure to store a step's records fails the run, not the node.
        with pytest.raises(WorkflowError) as raised:
            async for _ in workflow.invoke(event):
                pass
    assert not isinstance(raised.value, NodeExecutionError)
    assert raised.value.__cause__ is failure
    history = await event_store.get_agent_events("r")
    assert not any(isinstance(record, ConsumeFromTopicEvent) for record in history)
    assert len(failed_batches) == 1
    assert (
        sum(isinstance(record, ConsumeFromTopicEvent) for record in failed_batches[0])
        == 2
    )
    assert (
        sum(isinstance(record, PublishToTopicEvent) for record in failed_batches[0])
        == 6
    )
    async with asyncio.timeout(3):
        outputs = [output async for output in workflow.invoke(event)]
    assert len(outputs) == 6
    assert tool.calls == 2


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
    with pytest.raises(WorkflowError, match="history.*consumed offset 2"):
        async with asyncio.timeout(5):
            async for _ in workflow.invoke(event):
                pass
    assert len(await topic_history(event_store)) == 2


@pytest.mark.asyncio
async def test_sequential_recovery_runs_ready_nodes_in_definition_order(
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
    async with asyncio.timeout(5):
        outputs = [output async for output in definition.invoke(event, True)]
    assert len(outputs) == 6
    publishers = [
        record.publisher_name
        for record in sorted(
            (
                record
                for record in await event_store.get_agent_events("r")
                if isinstance(record, PublishToTopicEvent) and record.name == "out"
            ),
            key=lambda record: record.offset,
        )
    ]
    assert publishers == ["first"] * 3 + ["second"] * 3
