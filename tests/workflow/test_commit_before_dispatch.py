"""Parallel steps commit before their publications become visible downstream."""

import asyncio
from typing import Any
from typing import List
from typing import Optional
from typing import Sequence

import pytest
from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.component_events import NodeFailedEvent
from grafi.common.events.component_events import WorkflowFailedEvent
from grafi.common.events.event import Event
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.exceptions import WorkflowError
from grafi.common.models.async_result import async_func_wrapper
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
from tests_integration.async_execution.support import input_event


class ScriptedTool(Tool):
    """Runs an async script per call; the script yields message batches."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    script: Any = Field(default=None, exclude=True)
    calls: list[list[str]] = Field(default_factory=list)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        contents = [str(message.content) for message in input_data]
        self.calls.append(contents)
        async for batch in self.script(len(self.calls), contents):
            yield batch


def reply(*texts: str, streaming: bool = False) -> Messages:
    return [Message(role="assistant", content=t, is_streaming=streaming) for t in texts]


def node(name: str, tool: Tool, source: TopicBase, *destinations: TopicBase) -> Node:
    return Node(
        name=name,
        tool=tool,
        subscribed_expressions=[TopicExpr(topic=source)],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=destination) for destination in destinations]
        ),
    )


async def until_run_failed(workflow: EventDrivenWorkflow) -> None:
    """Wait until the workflow's run has recorded its failure."""
    async with asyncio.timeout(5):
        while not any(run._failure for run in workflow._active_runs.values()):
            await asyncio.sleep(0.001)


async def drain(workflow: EventDrivenWorkflow, event: PublishToTopicEvent) -> list[str]:
    async with asyncio.timeout(5):
        return [str(o.data[0].content) async for o in workflow.invoke(event)]


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_single_producer_output_still_streams_before_step_commits(
    sequential: bool,
) -> None:
    first_seen = asyncio.Event()

    async def stream(call: int, inputs: list[str]) -> Any:
        yield reply("one", streaming=True)
        # Deadlocks unless "one" reaches the caller before this step finishes.
        await first_seen.wait()
        yield reply("two", streaming=True)

    tool = ScriptedTool(script=stream)
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("llm", tool, InputTopic(name="input"), OutputTopic(name="out")))
        .build()
    )
    received = []
    async with asyncio.timeout(5):
        async for output in workflow.invoke(input_event(), sequential):
            received.append(output.data[0].content)
            first_seen.set()
    assert received == ["one", "two"]


@pytest.mark.asyncio
async def test_failed_producer_on_shared_output_topic_leaves_no_gap(
    event_store: EventStore,
) -> None:
    b_done = asyncio.Event()
    original_record = event_store.record_events

    async def record(events: Sequence[Event]) -> None:
        await original_record(events)
        if any(getattr(e, "publisher_name", "") == "b" for e in events):
            b_done.set()

    event_store.record_events = record  # type: ignore[method-assign]

    async def a_script(call: int, inputs: list[str]) -> Any:
        yield reply("a1", streaming=True)
        if call == 1:
            await b_done.wait()
            raise RuntimeError("a failed")
        yield reply("a2", streaming=True)

    async def b_script(call: int, inputs: list[str]) -> Any:
        yield reply("b")

    out = OutputTopic(name="out")
    source = InputTopic(name="input")
    a, b = ScriptedTool(script=a_script), ScriptedTool(script=b_script)
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("a", a, source, out))
        .node(node("b", b, source, out))
        .build()
    )
    event = input_event()
    received: list[str] = []
    async with asyncio.timeout(5):
        with pytest.raises(NodeExecutionError, match="a failed"):
            async for output in workflow.invoke(event):
                received.append(str(output.data[0].content))
    # Two producers share the output topic, so A's chunks were staged: the caller
    # never saw output from the failed attempt.
    assert "a1" not in received
    history = await event_store.get_agent_events(
        event.invoke_context.assistant_request_id
    )
    assert [
        (r.offset, r.data[0].content)
        for r in history
        if isinstance(r, PublishToTopicEvent) and r.name == "out"
    ] == [(0, "b")]
    retried = await drain(workflow, event)
    assert retried == ["a1", "a2"] or sorted(retried) == ["a1", "a2", "b"]
    assert len(a.calls) == 2 and len(b.calls) == 1


@pytest.mark.asyncio
async def test_concurrent_producers_commit_contiguous_positions(
    event_store: EventStore,
) -> None:
    producers = 8

    async def emit(call: int, inputs: list[str]) -> Any:
        for index in range(3):
            await asyncio.sleep(0)
            yield reply(f"{inputs[0]}-{index}", streaming=True)

    async def sink(call: int, inputs: list[str]) -> Any:
        yield reply(*inputs)

    source, mid, out = (
        InputTopic(name="input"),
        Topic(name="mid"),
        OutputTopic(name="out"),
    )
    builder = EventDrivenWorkflow.builder()
    for index in range(producers):
        builder.node(node(f"p{index}", ScriptedTool(script=emit), source, mid))
    builder.node(node("sink", ScriptedTool(script=sink), mid, out))
    workflow = builder.build()
    event = input_event("seed")
    async with asyncio.timeout(5):
        outputs = [
            str(message.content)
            async for output in workflow.invoke(event)
            for message in output.data
        ]
    assert sorted(outputs) == sorted(
        f"seed-{index}" for _ in range(producers) for index in range(3)
    )
    history = await event_store.get_agent_events(
        event.invoke_context.assistant_request_id
    )
    offsets = sorted(
        r.offset
        for r in history
        if isinstance(r, PublishToTopicEvent) and r.name == "mid"
    )
    assert offsets == list(range(producers * 3))
    consumed = sorted(
        r.offset
        for r in history
        if isinstance(r, ConsumeFromTopicEvent) and r.name == "mid"
    )
    assert consumed == offsets
    # The recorded history restores without gaps or conflicting positions, and
    # resuming the finished request has nothing left to run or deliver.
    assert await drain(workflow, event) == []


def test_streamed_topics_are_single_producer_workflow_outputs() -> None:
    async def noop(call: int, inputs: list[str]) -> Any:
        yield reply("x")

    from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic

    source, mid = InputTopic(name="input"), Topic(name="mid")
    solo, shared = OutputTopic(name="solo"), OutputTopic(name="shared")
    request = InWorkflowOutputTopic(name="request")  # Answered later by event ID.
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("a", ScriptedTool(script=noop), source, solo, shared, mid, request))
        .node(node("b", ScriptedTool(script=noop), mid, shared))
        .build()
    )
    assert workflow._streamed_topics == {"solo"}


@pytest.mark.asyncio
async def test_commit_write_that_lands_but_reports_failure_is_not_rerun(
    event_store: EventStore,
) -> None:
    original_record = event_store.record_events
    lost: list[str] = []

    async def lost_response(events: Sequence[Event]) -> None:
        await original_record(events)  # The write lands...
        if not lost and any(getattr(e, "publisher_name", "") == "a" for e in events):
            lost.append("a")
            raise ConnectionResetError("response lost")  # ...but reports failure.

    event_store.record_events = lost_response  # type: ignore[method-assign]

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("y")

    async def echo(call: int, inputs: list[str]) -> Any:
        yield reply("|".join(inputs))

    producer, mid = ScriptedTool(script=emit), Topic(name="mid")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("a", producer, InputTopic(name="input"), mid))
        .node(node("b", ScriptedTool(script=echo), mid, OutputTopic(name="out")))
        .build()
    )
    event = input_event()
    # A failed write of a step's records fails the run, so no later step can
    # take the positions it may have written.
    with pytest.raises(WorkflowError) as raised:
        await drain(workflow, event)
    assert not isinstance(raised.value, NodeExecutionError)
    assert isinstance(raised.value.__cause__, ConnectionResetError)
    # Resuming finds the step stored: it is not run again, and its publication
    # keeps its position.
    assert await drain(workflow, event) == ["y"]
    assert len(producer.calls) == 1
    stored = [
        r.offset
        for r in await event_store.get_events()
        if isinstance(r, PublishToTopicEvent) and r.name == "mid"
    ]
    assert stored == [0]


@pytest.mark.asyncio
async def test_first_node_failure_in_time_is_surfaced() -> None:
    b_failed = asyncio.Event()

    async def a_script(call: int, inputs: list[str]) -> Any:
        await b_failed.wait()
        raise RuntimeError("a failed later")
        yield reply("x")

    async def b_script(call: int, inputs: list[str]) -> Any:
        b_failed.set()
        raise RuntimeError("b failed first")
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("a", ScriptedTool(script=a_script), source, OutputTopic(name="o1")))
        .node(node("b", ScriptedTool(script=b_script), source, OutputTopic(name="o2")))
        .build()
    )
    with pytest.raises(NodeExecutionError, match="b failed first"):
        await drain(workflow, input_event())


async def drain_mode(
    workflow: EventDrivenWorkflow, event: PublishToTopicEvent, sequential: bool
) -> list[Any]:
    async with asyncio.timeout(5):
        return [o async for o in workflow.invoke(event, sequential)]


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_human_request_received_before_break_can_be_answered(
    event_store: EventStore, sequential: bool
) -> None:
    from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
    from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic

    async def ask(call: int, inputs: list[str]) -> Any:
        yield reply("what is your name?")

    async def answer(call: int, inputs: list[str]) -> Any:
        yield reply("got:" + "|".join(inputs))

    response = InWorkflowInputTopic(name="human_response")
    request = InWorkflowOutputTopic(
        name="human_request", paired_in_workflow_input_topic_names=["human_response"]
    )
    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node("asker", ScriptedTool(script=ask), InputTopic(name="input"), request)
        )
        .node(
            node(
                "answerer",
                ScriptedTool(script=answer),
                response,
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    first = input_event("register me")
    async with asyncio.timeout(5):
        outputs = workflow.invoke(first, sequential)
        prompt = await anext(outputs)
        await outputs.aclose()  # The caller stops as soon as it has the prompt.
    assert prompt.data[0].content == "what is your name?"
    resume = input_event("Alice").model_copy(
        update={
            "invoke_context": first.invoke_context,
            "consumed_event_ids": [prompt.event_id],
        }
    )
    async with asyncio.timeout(5):
        answers = [o.data[0].content async for o in workflow.invoke(resume, sequential)]
    assert answers == ["got:Alice"]


@pytest.mark.asyncio
async def test_cleanup_failure_is_kept_on_the_node_failure(
    event_store: EventStore,
) -> None:
    received = asyncio.Event()
    original_record = event_store.record_events

    emitted = asyncio.Event()

    async def record(events: Sequence[Event]) -> None:
        if any(
            isinstance(e, ConsumeFromTopicEvent) and e.consumer_name for e in events
        ) and all(
            isinstance(e, ConsumeFromTopicEvent) and e.name == "out" for e in events
        ):
            raise OSError("acknowledgement write failed")
        await original_record(events)
        if any(isinstance(e, PublishToTopicEvent) and e.name == "out" for e in events):
            emitted.set()  # The emitting step committed.

    event_store.record_events = record  # type: ignore[method-assign]

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("ok")

    async def fail(call: int, inputs: list[str]) -> Any:
        await received.wait()
        raise RuntimeError("node failed")
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("emit", ScriptedTool(script=emit), source, OutputTopic(name="out")))
        .node(node("fail", ScriptedTool(script=fail), source, OutputTopic(name="o2")))
        .build()
    )
    with pytest.raises(NodeExecutionError, match="node failed") as raised:
        async with asyncio.timeout(5):
            async for output in workflow.invoke(input_event()):
                await emitted.wait()
                received.set()
    notes = getattr(raised.value, "__notes__", [])
    assert any("acknowledgement write failed" in note for note in notes)


class Interrupt(BaseException):
    """Stands in for KeyboardInterrupt, which asyncio re-raises out of the loop."""


@pytest.mark.asyncio
async def test_interrupt_during_cleanup_outranks_the_node_failure(
    event_store: EventStore,
) -> None:
    received = asyncio.Event()
    original_record = event_store.record_events

    emitted = asyncio.Event()

    async def record(events: Sequence[Event]) -> None:
        if events and all(
            isinstance(e, ConsumeFromTopicEvent) and e.name == "out" for e in events
        ):
            raise Interrupt("interrupted while acknowledging outputs")
        await original_record(events)
        if any(isinstance(e, PublishToTopicEvent) and e.name == "out" for e in events):
            emitted.set()  # The emitting step committed.

    event_store.record_events = record  # type: ignore[method-assign]

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("ok")

    async def fail(call: int, inputs: list[str]) -> Any:
        await received.wait()
        raise RuntimeError("node failed")
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("emit", ScriptedTool(script=emit), source, OutputTopic(name="out")))
        .node(node("fail", ScriptedTool(script=fail), source, OutputTopic(name="o2")))
        .build()
    )
    with pytest.raises(Interrupt) as raised:
        async with asyncio.timeout(5):
            async for output in workflow.invoke(input_event()):
                await emitted.wait()
                received.set()
    # The run's failure stays visible on the interrupt that outranks it.
    notes = getattr(raised.value, "__notes__", [])
    assert any("node failed" in note for note in notes)


@pytest.mark.asyncio
async def test_interrupt_during_cleanup_outranks_a_later_cancellation(
    event_store: EventStore,
) -> None:
    original_record = event_store.record_events
    emitted, interrupted = asyncio.Event(), asyncio.Event()
    slow_started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def record(events: Sequence[Event]) -> None:
        if events and all(
            isinstance(e, ConsumeFromTopicEvent) and e.name == "out" for e in events
        ):
            interrupted.set()
            raise Interrupt("interrupted while acknowledging outputs")
        await original_record(events)
        if any(isinstance(e, PublishToTopicEvent) and e.name == "out" for e in events):
            emitted.set()  # The emitting step committed.

    event_store.record_events = record  # type: ignore[method-assign]

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("ok")

    async def slow(call: int, inputs: list[str]) -> Any:
        slow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            raise
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("emit", ScriptedTool(script=emit), source, OutputTopic(name="out")))
        .node(node("slow", ScriptedTool(script=slow), source, OutputTopic(name="o2")))
        .build()
    )
    outputs = workflow.invoke(input_event())
    async with asyncio.timeout(5):
        await anext(outputs)
        await asyncio.gather(emitted.wait(), slow_started.wait())
        closing = asyncio.create_task(outputs.aclose())
        await cleaning.wait()
        release.set()  # The steps stop, then the close acknowledges outputs.
        await interrupted.wait()
        closing.cancel()  # A timeout around the close, after the interrupt.
        await asyncio.wait({closing})
    assert not closing.cancelled()
    assert isinstance(closing.exception(), Interrupt)


@pytest.mark.asyncio
async def test_timeout_during_acknowledgement_still_bounds_the_close(
    event_store: EventStore,
) -> None:
    original_record = event_store.record_events
    emitted, acknowledging = asyncio.Event(), asyncio.Event()
    slow_started = asyncio.Event()

    async def record(events: Sequence[Event]) -> None:
        if events and all(
            isinstance(e, ConsumeFromTopicEvent) and e.name == "out" for e in events
        ):
            acknowledging.set()
            await asyncio.Event().wait()  # A slow write, cut short by the timeout.
        await original_record(events)
        if any(isinstance(e, PublishToTopicEvent) and e.name == "out" for e in events):
            emitted.set()  # The emitting step committed.

    event_store.record_events = record  # type: ignore[method-assign]

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("ok")

    async def slow(call: int, inputs: list[str]) -> Any:
        slow_started.set()
        await asyncio.Event().wait()  # Stopped by the close.
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("emit", ScriptedTool(script=emit), source, OutputTopic(name="out")))
        .node(node("slow", ScriptedTool(script=slow), source, OutputTopic(name="o2")))
        .build()
    )

    async def read_then_close() -> None:
        outputs = workflow.invoke(input_event())
        await anext(outputs)
        await asyncio.gather(emitted.wait(), slow_started.wait())
        await outputs.aclose()  # Stops the steps, then acknowledges "ok".

    caller = asyncio.create_task(read_then_close())
    try:
        async with asyncio.timeout(2):
            await acknowledging.wait()
        caller.cancel()  # A timeout around the close lands in the write.
        await asyncio.wait({caller}, timeout=2)
        assert caller.cancelled()
    finally:
        caller.cancel()
        await asyncio.wait({caller})


@pytest.mark.asyncio
async def test_ack_failing_during_the_cancellation_does_not_cancel_nodes_twice(
    event_store: EventStore,
) -> None:
    original_record = event_store.record_events
    emitted, slow_started = asyncio.Event(), asyncio.Event()
    cleanup: list[str] = []

    async def record(events: Sequence[Event]) -> None:
        if events and all(
            isinstance(e, ConsumeFromTopicEvent) and e.name == "out" for e in events
        ):
            raise RuntimeError("database error")  # Left by the cancellation.
        await original_record(events)
        if any(isinstance(e, PublishToTopicEvent) and e.name == "out" for e in events):
            emitted.set()

    event_store.record_events = record  # type: ignore[method-assign]

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("ok")

    async def slow(call: int, inputs: list[str]) -> Any:
        slow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)  # Releases a client; interrupted if cancelled.
            cleanup.append("completed")
            raise
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("emit", ScriptedTool(script=emit), source, OutputTopic(name="out")))
        .node(node("slow", ScriptedTool(script=slow), source, OutputTopic(name="o2")))
        .build()
    )

    received = asyncio.Event()

    async def read_all() -> None:
        async for _ in workflow.invoke(input_event()):
            received.set()  # Handed over, so the close acknowledges it.

    caller = asyncio.create_task(read_all())
    async with asyncio.timeout(5):
        await asyncio.gather(emitted.wait(), slow_started.wait(), received.wait())
        caller.cancel()  # Once: the teardown cancels the nodes once.
        await asyncio.wait({caller})
    assert caller.cancelled()
    assert cleanup == ["completed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_cancel_count_a_tool_leaves_does_not_hide_a_later_failure(
    sequential: bool,
) -> None:
    async def leaves_a_count_then_fails(call: int, inputs: list[str]) -> Any:
        if call == 2:
            raise ValueError("real failure")
        task = asyncio.current_task()
        assert task is not None
        task.cancel()  # A tool's own timeout...
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass  # ...swallowed without uncancel().
        yield reply("again")

    again = Topic(name="again")
    a = Node(
        name="a",
        tool=ScriptedTool(script=leaves_a_count_then_fails),
        subscribed_expressions=[
            SubscriptionBuilder()
            .subscribed_to(InputTopic(name="input"))
            .or_()
            .subscribed_to(again)
            .build()
        ],
        publisher_router=PublisherRouter(
            routes=[
                PublishRoute(topic=again),
                PublishRoute(topic=OutputTopic(name="out")),
            ]
        ),
    )
    workflow = EventDrivenWorkflow.builder().node(a).build()

    async def run_it() -> int:
        with pytest.raises(NodeExecutionError, match="real failure"):
            await drain_mode(workflow, input_event(), sequential)
        task = asyncio.current_task()
        assert task is not None
        return task.cancelling()

    # Each step runs in a task the run owns, so the count stays with that step
    # and never reaches the caller's task.
    assert await asyncio.create_task(run_it()) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_tools_own_timeout_around_a_nested_workflow_still_fires(
    sequential: bool,
) -> None:
    async def blocks(call: int, inputs: list[str]) -> Any:
        await asyncio.Event().wait()
        yield reply("never")

    inner = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "inner",
                ScriptedTool(script=blocks),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )

    async def calls_the_inner_workflow(call: int, inputs: list[str]) -> Any:
        try:
            async with asyncio.timeout(0.05):
                async for _ in inner.invoke(input_event(), sequential):
                    pass
        except TimeoutError:
            yield reply("timed out")  # The tool's own timeout worked.

    outer = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "agent",
                ScriptedTool(script=calls_the_inner_workflow),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    assert await drain(outer, input_event()) == ["timed out"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_ack_failing_during_the_callers_cancellation_keeps_it(
    event_store: EventStore, sequential: bool
) -> None:
    original_record = event_store.record_events

    async def record(events: Sequence[Event]) -> None:
        if events and all(
            isinstance(e, ConsumeFromTopicEvent) and e.name == "out" for e in events
        ):
            try:
                raise OSError("connection reset")
            except OSError as inner:  # A driver's error mapping.
                raise RuntimeError("store failed") from inner
        await original_record(events)

    event_store.record_events = record  # type: ignore[method-assign]

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("ok")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "emit",
                ScriptedTool(script=emit),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    received = asyncio.Event()
    seen: list[tuple[Any, ...]] = []

    async def read_then_wait() -> None:
        outputs = workflow.invoke(input_event(), sequential)
        try:
            await anext(outputs)
            received.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError as cancellation:
            seen.append(cancellation.args)
            raise
        finally:
            await outputs.aclose()

    async def caller() -> None:
        try:
            await read_then_wait()
        except asyncio.CancelledError as cancellation:
            seen.append(cancellation.args)
            raise

    task = asyncio.create_task(caller())
    async with asyncio.timeout(5):
        await received.wait()
        task.cancel("shutdown")
        await asyncio.wait({task})
    # The close's acknowledgement failure did not replace the cancellation.
    assert seen == [("shutdown",), ("shutdown",)]


@pytest.mark.asyncio
async def test_run_started_in_a_withdrawn_cancellation_sees_a_later_one() -> None:
    resumed = asyncio.Event()

    async def emit_then_wait(call: int, inputs: list[str]) -> Any:
        yield reply("a")
        await asyncio.Event().wait()
        yield reply("never")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "emit",
                ScriptedTool(script=emit_then_wait),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )

    async def caller() -> None:
        try:
            async with asyncio.timeout(0.01):
                try:
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    # Started while the timeout's cancellation is handled...
                    outputs = workflow.invoke(input_event())
                    await anext(outputs)
                    raise  # ...which the timeout then withdraws.
        except TimeoutError:
            resumed.set()
        try:
            await anext(outputs)  # Cancelled here for real.
        finally:
            await outputs.aclose()

    task = asyncio.create_task(caller())
    async with asyncio.timeout(5):
        await resumed.wait()  # The caller now waits for the next output.
        task.cancel()
        await asyncio.wait({task})
    assert task.cancelled()  # Not mistaken for a failed output read.


@pytest.mark.asyncio
async def test_node_ending_with_an_interrupt_as_it_stops_fails_the_close() -> None:
    async def emits_then_waits(call: int, inputs: list[str]) -> Any:
        yield reply("ok")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise Interrupt("interrupted while stopping")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "emit",
                ScriptedTool(script=emits_then_waits),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    outputs = workflow.invoke(input_event())
    async with asyncio.timeout(5):
        await anext(outputs)
        with pytest.raises(Interrupt):  # Not dropped as stopping's fallout.
            await outputs.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_step_ending_with_an_interrupt_outranks_the_callers_cancel(
    sequential: bool,
) -> None:
    started = asyncio.Event()

    async def interrupted_when_cancelled(call: int, inputs: list[str]) -> Any:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise Interrupt("interrupted while stopping")
        yield reply("never")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "slow",
                ScriptedTool(script=interrupted_when_cancelled),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    task = asyncio.create_task(drain_mode(workflow, input_event(), sequential))
    async with asyncio.timeout(5):
        await started.wait()
        task.cancel()
        await asyncio.wait({task})
    assert not task.cancelled()
    assert isinstance(task.exception(), Interrupt)


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_tool_raising_cancelled_error_on_its_own_fails_the_run(
    sequential: bool, event_store: EventStore
) -> None:
    async def cancelled(call: int, inputs: list[str]) -> Any:
        raise asyncio.CancelledError()  # For example a transport's own timeout.
        yield reply("x")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "llm",
                ScriptedTool(script=cancelled),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    with pytest.raises(NodeExecutionError, match="unexpectedly cancelled") as raised:
        await drain_mode(workflow, input_event(), sequential)
    assert raised.value.node_name == "llm"
    cause = raised.value.__cause__
    assert isinstance(cause, RuntimeError)
    assert isinstance(cause.__cause__, asyncio.CancelledError)
    # Recorded as the node's failure and the workflow's.
    events = await event_store.get_events()
    assert [e.name for e in events if isinstance(e, NodeFailedEvent)] == ["llm"]
    assert len([e for e in events if isinstance(e, WorkflowFailedEvent)]) == 1


@pytest.mark.asyncio
async def test_failure_caused_by_teardown_is_not_raised_on_close() -> None:
    slow_started = asyncio.Event()

    async def emit(call: int, inputs: list[str]) -> Any:
        await slow_started.wait()
        yield reply("ok")

    async def slow(call: int, inputs: list[str]) -> Any:
        slow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # A transport that reports its cancellation as an error.
            raise ConnectionError("transport closed")
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("emit", ScriptedTool(script=emit), source, OutputTopic(name="out")))
        .node(node("slow", ScriptedTool(script=slow), source, OutputTopic(name="o2")))
        .build()
    )
    messages: list[str] = []
    handler = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    outputs = workflow.invoke(input_event())
    try:
        async with asyncio.timeout(5):
            assert (await anext(outputs)).data[0].content == "ok"
            await outputs.aclose()  # The caller is done; teardown is not a failure.
    finally:
        logger.remove(handler)
    # Not raised, but not silent either.
    assert any("Not raised" in m and "transport closed" in m for m in messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_timeout_a_store_reports_as_an_error_stays_a_timeout(
    event_store: EventStore, sequential: bool
) -> None:
    original_record = event_store.record_events

    async def record(events: Sequence[Event]) -> None:
        if events and all(
            isinstance(e, ConsumeFromTopicEvent) and e.name == "out" for e in events
        ):
            try:
                await asyncio.Event().wait()  # The acknowledgement write is slow.
            except asyncio.CancelledError:
                raise RuntimeError("driver reports cancellation")
        await original_record(events)

    event_store.record_events = record  # type: ignore[method-assign]

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("x")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "emit",
                ScriptedTool(script=emit),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.2):
            async for _ in workflow.invoke(input_event(), sequential):
                pass


@pytest.mark.asyncio
async def test_async_result_close_raises_a_node_failure_like_the_generator() -> None:
    caller_has_output = asyncio.Event()

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("ok")

    async def fail(call: int, inputs: list[str]) -> Any:
        await caller_has_output.wait()
        raise RuntimeError("node failed")
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("emit", ScriptedTool(script=emit), source, OutputTopic(name="out")))
        .node(node("fail", ScriptedTool(script=fail), source, OutputTopic(name="o2")))
        .build()
    )
    result = async_func_wrapper(workflow.invoke(input_event()))
    async with asyncio.timeout(5):
        assert (await anext(result)).data[0].content == "ok"
        caller_has_output.set()
        await until_run_failed(workflow)  # The node fails while the caller waits.
        with pytest.raises(NodeExecutionError, match="node failed"):
            await result.aclose()


@pytest.mark.asyncio
async def test_async_result_read_cancelled_as_the_run_fails_notes_the_failure() -> None:
    slow_started, cleaning = asyncio.Event(), asyncio.Event()
    release = asyncio.Event()

    async def fail(call: int, inputs: list[str]) -> Any:
        await slow_started.wait()
        raise RuntimeError("node failed")
        yield reply("x")

    async def slow(call: int, inputs: list[str]) -> Any:
        slow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()  # Still cleaning up when the read is cancelled.
            raise
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("fail", ScriptedTool(script=fail), source, OutputTopic(name="out")))
        .node(node("slow", ScriptedTool(script=slow), source, OutputTopic(name="o2")))
        .build()
    )
    result = async_func_wrapper(workflow.invoke(input_event()))
    notes: list[str] = []

    async def read() -> Any:
        try:
            return await anext(result)
        except asyncio.CancelledError as error:
            notes.extend(getattr(error, "__notes__", []))
            raise

    async with asyncio.timeout(5):
        reading = asyncio.create_task(read())
        await cleaning.wait()  # The run failed and is tearing down.
        reading.cancel()  # A per-item timeout: the read closes the source.
        release.set()
        await asyncio.wait({reading})
        assert reading.cancelled()
        # The failure is attached to the cancellation, not raised, and the
        # result, cut short, never looks complete.
        await result.aclose()
        with pytest.raises(RuntimeError, match="closed before its stream finished"):
            await anext(result)
    assert any("Workflow failure" in n and "node failed" in n for n in notes)


class ShoutingTopic(Topic):
    """Customizes its publications through the hook every run uses."""

    def prepare_publication(
        self, publish_event: PublishToTopicEvent
    ) -> PublishToTopicEvent:
        publication = super().prepare_publication(publish_event)
        for message in publication.data:
            message.content = str(message.content).upper()
        return publication


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_topic_publication_hooks_apply_in_both_modes(sequential: bool) -> None:
    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("x")

    async def echo(call: int, inputs: list[str]) -> Any:
        yield reply("|".join(inputs))

    mid = ShoutingTopic(name="mid")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node("producer", ScriptedTool(script=emit), InputTopic(name="input"), mid)
        )
        .node(node("sink", ScriptedTool(script=echo), mid, OutputTopic(name="out")))
        .build()
    )
    outputs = await drain_mode(workflow, input_event(), sequential)
    assert [o.data[0].content for o in outputs] == ["X"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_error_raised_by_the_callers_cancellation_lets_it_win(
    sequential: bool,
) -> None:
    async def slow(call: int, inputs: list[str]) -> Any:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # A transport that reports its cancellation as an error.
            raise ConnectionError("connection reset")
        yield reply("x")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "llm",
                ScriptedTool(script=slow),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.2):
            async for _ in workflow.invoke(input_event(), sequential):
                pass


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_node_ending_with_a_base_exception_fails_the_run(
    sequential: bool,
) -> None:
    async def aborts(call: int, inputs: list[str]) -> Any:
        yield reply("partial")
        raise Interrupt("node aborted")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "llm",
                ScriptedTool(script=aborts),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    with pytest.raises(Interrupt, match="node aborted"):
        await drain_mode(workflow, input_event(), sequential)


@pytest.mark.asyncio
async def test_real_failure_during_a_requested_stop_is_raised(
    event_store: EventStore,
) -> None:
    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("x")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "producer",
                ScriptedTool(script=emit),
                InputTopic(name="input"),
                Topic(name="mid"),
            )
        )
        .node(
            node(
                "sink",
                ScriptedTool(script=emit),
                Topic(name="mid"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    original_record = event_store.record_events

    async def record(events: Sequence[Event]) -> None:
        if any(isinstance(e, PublishToTopicEvent) and e.name == "mid" for e in events):
            workflow.stop()  # The caller asks the run to stop ...
            raise OSError("store down")  # ... as the step's write really fails.
        await original_record(events)

    event_store.record_events = record  # type: ignore[method-assign]
    # A failure to store a step's records fails the run, not the node.
    with pytest.raises(WorkflowError, match="store down") as raised:
        await drain_mode(workflow, input_event(), False)
    assert not isinstance(raised.value, NodeExecutionError)
    assert isinstance(raised.value.__cause__, OSError)


@pytest.mark.asyncio
async def test_run_failure_survives_a_cancellation_while_steps_stop() -> None:
    slow_started, stopping, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def fail(call: int, inputs: list[str]) -> Any:
        await slow_started.wait()
        raise RuntimeError("node failed")
        yield reply("x")

    async def slow(call: int, inputs: list[str]) -> Any:
        slow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopping.set()  # The failed run is waiting for this step to end.
            await release.wait()  # A slow cleanup.
            raise
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("fail", ScriptedTool(script=fail), source, OutputTopic(name="o1")))
        .node(node("slow", ScriptedTool(script=slow), source, OutputTopic(name="o2")))
        .build()
    )
    notes: list[str] = []

    async def consume() -> None:
        try:
            async for _ in workflow.invoke(input_event()):
                pass
        except asyncio.CancelledError as error:
            notes.extend(getattr(error, "__notes__", []))
            raise

    caller = asyncio.create_task(consume())
    async with asyncio.timeout(5):
        await stopping.wait()
        caller.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
    assert any("node failed" in note for note in notes)


@pytest.mark.asyncio
async def test_sequential_run_keeps_the_callers_cancellation_message() -> None:
    started = asyncio.Event()

    async def slow(call: int, inputs: list[str]) -> Any:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise ConnectionError("connection reset")
        yield reply("x")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "llm",
                ScriptedTool(script=slow),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    seen: list[tuple[Any, ...]] = []

    async def caller() -> None:
        try:
            async for _ in workflow.invoke(input_event(), True):
                pass
        except asyncio.CancelledError as error:
            seen.append(error.args)
            raise

    task = asyncio.create_task(caller())
    async with asyncio.timeout(5):
        await started.wait()
        task.cancel(msg="shutdown")
        with pytest.raises(asyncio.CancelledError):
            await task
    assert seen == [("shutdown",)]


@pytest.mark.asyncio
async def test_teardown_error_of_another_node_is_not_noted_as_a_failure() -> None:
    slow_started = asyncio.Event()

    async def fail(call: int, inputs: list[str]) -> Any:
        await slow_started.wait()
        raise RuntimeError("node failed")
        yield reply("x")

    async def slow(call: int, inputs: list[str]) -> Any:
        slow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise ConnectionError("transport closed")  # Reports the teardown.
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("fail", ScriptedTool(script=fail), source, OutputTopic(name="o1")))
        .node(node("slow", ScriptedTool(script=slow), source, OutputTopic(name="o2")))
        .build()
    )
    with pytest.raises(NodeExecutionError, match="node failed") as raised:
        await drain(workflow, input_event())
    notes = getattr(raised.value, "__notes__", [])
    assert not any("transport closed" in note for note in notes)


class OverridesPublishData(Topic):
    async def publish_data(
        self, publish_event: PublishToTopicEvent
    ) -> PublishToTopicEvent:
        return await super().publish_data(publish_event)


class OverridesAddEvent(Topic):
    async def add_event(self, event: TopicEvent) -> Optional[TopicEvent]:
        return await super().add_event(event)


class OverridesConsume(Topic):
    async def consume(
        self, consumer_name: str, timeout: Optional[float] = None
    ) -> List[TopicEvent]:
        return await super().consume(consumer_name, timeout)


@pytest.mark.parametrize(
    "Redacting, method",
    [
        (OverridesPublishData, "publish_data"),
        (OverridesAddEvent, "add_event"),
        (OverridesConsume, "consume"),
    ],
)
def test_topic_overriding_a_method_runs_skip_is_rejected(
    Redacting: type, method: str
) -> None:

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("x")

    with pytest.raises(WorkflowError, match=f"overrides {method}"):
        (
            EventDrivenWorkflow.builder()
            .node(
                node(
                    "producer",
                    ScriptedTool(script=emit),
                    InputTopic(name="input"),
                    Redacting(name="mid"),
                )
            )
            .node(
                node(
                    "sink",
                    ScriptedTool(script=emit),
                    Redacting(name="mid"),
                    OutputTopic(name="out"),
                )
            )
            .build()
        )


@pytest.mark.asyncio
async def test_acknowledgement_write_cancelled_by_nobody_keeps_the_node_failure(
    event_store: EventStore,
) -> None:
    received = asyncio.Event()
    original_record = event_store.record_events

    async def record(events: Sequence[Event]) -> None:
        if events and all(
            isinstance(e, ConsumeFromTopicEvent) and e.name == "out" for e in events
        ):
            raise asyncio.CancelledError()  # For example a driver's own timeout.
        await original_record(events)

    event_store.record_events = record  # type: ignore[method-assign]

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("ok")

    async def fail(call: int, inputs: list[str]) -> Any:
        await received.wait()
        raise RuntimeError("node failed")
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("emit", ScriptedTool(script=emit), source, OutputTopic(name="out")))
        .node(node("fail", ScriptedTool(script=fail), source, OutputTopic(name="o2")))
        .build()
    )
    with pytest.raises(NodeExecutionError, match="node failed") as raised:
        async with asyncio.timeout(5):
            async for _ in workflow.invoke(input_event()):
                await until_emitted(event_store)
                received.set()
    notes = getattr(raised.value, "__notes__", [])
    assert any(
        "Later failure" in n and "Workflow run was unexpectedly cancelled" in n
        for n in notes
    )


async def until_emitted(event_store: EventStore) -> None:
    """Wait until the emitting step's publication is stored."""
    async with asyncio.timeout(5):
        while not any(
            isinstance(e, PublishToTopicEvent) and e.name == "out"
            for e in await event_store.get_events()
        ):
            await asyncio.sleep(0.001)


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_resending_the_same_human_answer_is_idempotent(
    event_store: EventStore, sequential: bool
) -> None:
    from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
    from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic

    async def ask(call: int, inputs: list[str]) -> Any:
        yield reply("what is your name?")

    async def answer(call: int, inputs: list[str]) -> Any:
        if call == 1:
            raise RuntimeError("answer failed")
        yield reply("got:" + "|".join(inputs))

    response = InWorkflowInputTopic(name="human_response")
    request = InWorkflowOutputTopic(
        name="human_request", paired_in_workflow_input_topic_names=["human_response"]
    )
    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node("asker", ScriptedTool(script=ask), InputTopic(name="input"), request)
        )
        .node(
            node(
                "answerer",
                ScriptedTool(script=answer),
                response,
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    first = input_event("register me")
    async with asyncio.timeout(5):
        outputs = workflow.invoke(first, sequential)
        prompt = await anext(outputs)
        await outputs.aclose()
    resume = input_event("Alice").model_copy(
        update={
            "invoke_context": first.invoke_context,
            "consumed_event_ids": [prompt.event_id],
        }
    )
    with pytest.raises(NodeExecutionError, match="answer failed"):
        await drain_mode(workflow, resume, sequential)
    # The same answer again (for example a client retry) is answered once.
    answers = [
        o.data[0].content for o in await drain_mode(workflow, resume, sequential)
    ]
    assert answers == ["got:Alice"]


@pytest.mark.asyncio
async def test_node_failure_outside_a_step_fails_the_run() -> None:
    class BadReadiness(Node):
        def can_invoke_with_topics(self, topics: list[str]) -> bool:
            if topics:
                raise NodeExecutionError(node_name=self.name, message="bad readiness")
            return False

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("ok")

    source, out = InputTopic(name="input"), OutputTopic(name="out")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("healthy", ScriptedTool(script=emit), source, out))
        .node(
            BadReadiness(
                name="bad",
                tool=ScriptedTool(script=emit),
                subscribed_expressions=[TopicExpr(topic=source)],
                publisher_router=PublisherRouter(routes=[PublishRoute(topic=out)]),
            )
        )
        .build()
    )
    with pytest.raises(NodeExecutionError, match="bad readiness"):
        await drain(workflow, input_event())


@pytest.mark.asyncio
async def test_commit_cancelled_by_nobody_fails_the_run(
    event_store: EventStore,
) -> None:
    original_record = event_store.record_events

    async def record(events: Sequence[Event]) -> None:
        if any(isinstance(e, PublishToTopicEvent) and e.name == "mid" for e in events):
            raise asyncio.CancelledError()  # The store's own timeout.
        await original_record(events)

    event_store.record_events = record  # type: ignore[method-assign]

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("x")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node(
                "producer",
                ScriptedTool(script=emit),
                InputTopic(name="input"),
                Topic(name="mid"),
            )
        )
        .node(
            node(
                "sink",
                ScriptedTool(script=emit),
                Topic(name="mid"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    # Not mistaken for a stop: the run fails, and its sink never runs.
    with pytest.raises(WorkflowError, match="unexpectedly cancelled") as raised:
        await drain(workflow, input_event())
    assert not isinstance(raised.value, NodeExecutionError)
    assert workflow.nodes["sink"].tool.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("close_hangs", [False, True])
async def test_failed_step_closes_normally_while_the_others_stop_at_once(
    close_hangs: bool,
) -> None:
    other_started, other_stopped = asyncio.Event(), asyncio.Event()
    closes: list[str] = []

    class Rejecting(Topic):
        def prepare_publication(
            self, publish_event: PublishToTopicEvent
        ) -> PublishToTopicEvent:
            raise ValueError("invalid publication")

    class Closing(Tool):
        oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

        async def invoke(
            self, invoke_context: InvokeContext, input_data: Messages
        ) -> MsgsAGen:
            await other_started.wait()
            try:
                yield reply("x")
            finally:
                await other_stopped.wait()  # The other step was stopped first.
                closes.append("closed")  # Not cut short by a cancellation.
                if close_hangs:
                    await asyncio.Event().wait()  # A close that never finishes.

    async def waits(call: int, inputs: list[str]) -> Any:
        other_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            other_stopped.set()
            raise
        yield reply("never")

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node("producer", Closing(), InputTopic(name="input"), Rejecting(name="mid"))
        )
        .node(
            node(
                "other",
                ScriptedTool(script=waits),
                InputTopic(name="input"),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    if close_hangs:
        # The run waits for the failed step's close; a timeout around the run
        # bounds it, and the caller's cancellation then stops that close too.
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.5):
                async for _ in workflow.invoke(input_event()):
                    pass
    else:
        with pytest.raises(NodeExecutionError, match="invalid publication"):
            async with asyncio.timeout(5):
                async for _ in workflow.invoke(input_event()):
                    pass
    assert closes == ["closed"]
    assert not workflow._active_runs


@pytest.mark.asyncio
async def test_teardown_lets_a_node_finish_its_cleanup() -> None:
    cleaned = asyncio.Event()

    class Streaming(Tool):
        oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

        async def invoke(
            self, invoke_context: InvokeContext, input_data: Messages
        ) -> MsgsAGen:
            try:
                yield reply("a", streaming=True)
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.05)  # For example releasing a client.
                cleaned.set()

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node("llm", Streaming(), InputTopic(name="input"), OutputTopic(name="out"))
        )
        .build()
    )
    outputs = workflow.invoke(input_event())
    async with asyncio.timeout(5):
        assert (await anext(outputs)).data[0].content == "a"
        await outputs.aclose()
    assert cleaned.is_set()  # Teardown cancels once, then waits.


@pytest.mark.asyncio
async def test_close_cancelled_while_steps_stop_leaves_outputs_for_resume(
    event_store: EventStore,
) -> None:
    slow_started, stopping = asyncio.Event(), asyncio.Event()

    async def ask(call: int, inputs: list[str]) -> Any:
        yield reply("what is your name?")

    async def slow(call: int, inputs: list[str]) -> Any:
        if call > 1:
            yield reply("x")  # Resumed: the stopped step runs again.
            return
        slow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopping.set()
            await asyncio.Event().wait()  # Stops only when cancelled again.
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("asker", ScriptedTool(script=ask), source, OutputTopic(name="out")))
        .node(node("slow", ScriptedTool(script=slow), source, OutputTopic(name="o2")))
        .build()
    )
    event = input_event()
    outputs = workflow.invoke(event)
    async with asyncio.timeout(5):
        assert (await anext(outputs)).data[0].content == "what is your name?"
        await asyncio.gather(until_emitted(event_store), slow_started.wait())
        closing = asyncio.create_task(outputs.aclose())
        await stopping.wait()
        closing.cancel()  # The caller's timeout lands while the steps stop.
        with pytest.raises(asyncio.CancelledError):
            await closing
    # The cancelled close aborted the run before it acknowledged the output, so
    # resuming delivers it again.
    history = await event_store.get_agent_events(
        event.invoke_context.assistant_request_id
    )
    assert not any(
        isinstance(record, ConsumeFromTopicEvent) and record.name == "out"
        for record in history
    )
    assert await drain(workflow, event) == ["what is your name?", "x"]


@pytest.mark.asyncio
async def test_an_answer_reusing_an_event_id_for_another_request_is_delivered(
    event_store: EventStore,
) -> None:
    from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
    from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic

    async def ask(call: int, inputs: list[str]) -> Any:
        yield reply("what is your name?")

    async def answer(call: int, inputs: list[str]) -> Any:
        if call == 1:
            raise RuntimeError("answer failed")
        yield reply("got:" + "|".join(inputs))

    response = InWorkflowInputTopic(name="human_response")
    request = InWorkflowOutputTopic(
        name="human_request", paired_in_workflow_input_topic_names=["human_response"]
    )
    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node("asker", ScriptedTool(script=ask), InputTopic(name="input"), request)
        )
        .node(
            node(
                "answerer",
                ScriptedTool(script=answer),
                response,
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    first = input_event("register me")
    async with asyncio.timeout(5):
        outputs = workflow.invoke(first)
        prompt = await anext(outputs)
        await outputs.aclose()
    alice = input_event("Alice").model_copy(
        update={
            "invoke_context": first.invoke_context,
            "consumed_event_ids": [prompt.event_id],
        }
    )
    with pytest.raises(NodeExecutionError, match="answer failed"):
        await drain_mode(workflow, alice, False)
    # The same event ID answering another request is a new input, not a resend.
    bob = alice.model_copy(
        update={
            "data": [Message(role="user", content="Bob")],
            "consumed_event_ids": [prompt.event_id, "another-request"],
        }
    )
    answers = [o.data[0].content for o in await drain_mode(workflow, bob, False)]
    assert answers == ["got:Alice|Bob"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_resent_answer_is_recognised_after_a_store_round_trip(
    event_store: EventStore, sequential: bool
) -> None:
    from pydantic import BaseModel

    from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
    from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic

    class Approval(BaseModel):
        approved: bool

    # Return events as a JSON store would, rebuilt from their stored form.
    get_agent_events = event_store.get_agent_events

    async def round_trip(request_id: str) -> list[Event]:
        return [
            decoded
            for event in await get_agent_events(request_id)
            if (decoded := event_store._create_event_from_dict(event.to_dict()))
        ]

    event_store.get_agent_events = round_trip  # type: ignore[method-assign]

    async def ask(call: int, inputs: list[str]) -> Any:
        yield reply("approve?")

    async def answer(call: int, inputs: list[str]) -> Any:
        if call == 1:
            raise RuntimeError("answer failed")
        yield reply(f"answers:{len(inputs)}")

    response = InWorkflowInputTopic(name="human_response")
    request = InWorkflowOutputTopic(
        name="human_request", paired_in_workflow_input_topic_names=["human_response"]
    )
    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            node("asker", ScriptedTool(script=ask), InputTopic(name="input"), request)
        )
        .node(
            node(
                "answerer",
                ScriptedTool(script=answer),
                response,
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    first = input_event("register me")
    async with asyncio.timeout(5):
        outputs = workflow.invoke(first, sequential)
        prompt = await anext(outputs)
        await outputs.aclose()
    approval = input_event("unused").model_copy(
        update={
            "invoke_context": first.invoke_context,
            "consumed_event_ids": [prompt.event_id],
            "data": [Message(role="user", content=Approval(approved=True))],
        }
    )
    with pytest.raises(NodeExecutionError, match="answer failed"):
        await drain_mode(workflow, approval, sequential)
    # The identical resend is answered once, though its data no longer
    # compares equal after the round trip.
    answers = [
        o.data[0].content for o in await drain_mode(workflow, approval, sequential)
    ]
    assert answers == ["answers:1"]


@pytest.mark.asyncio
async def test_callers_cancellation_keeps_the_acknowledgement_failure(
    event_store: EventStore,
) -> None:
    slow_started, received = asyncio.Event(), asyncio.Event()

    async def emit(call: int, inputs: list[str]) -> Any:
        yield reply("ok")

    async def slow(call: int, inputs: list[str]) -> Any:
        slow_started.set()
        await asyncio.Event().wait()  # Keeps the run going until it stops.
        yield reply("x")

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(node("emit", ScriptedTool(script=emit), source, OutputTopic(name="out")))
        .node(node("slow", ScriptedTool(script=slow), source, OutputTopic(name="o2")))
        .build()
    )
    original_record = event_store.record_events

    async def record(events: Sequence[Event]) -> None:
        if any(getattr(e, "consumer_name", None) == workflow.name for e in events):
            raise OSError("acknowledgement write failed")
        await original_record(events)

    event_store.record_events = record  # type: ignore[method-assign]
    notes: list[str] = []

    async def read_all() -> None:
        try:
            async for _ in workflow.invoke(input_event()):
                received.set()  # Handed over, so the close acknowledges it.
        except asyncio.CancelledError as error:
            notes.extend(getattr(error, "__notes__", []))
            raise

    caller = asyncio.create_task(read_all())
    async with asyncio.timeout(5):
        await asyncio.gather(received.wait(), slow_started.wait())
        caller.cancel()  # Stops the steps, then acknowledges "ok".
        await asyncio.wait({caller})
    assert caller.cancelled()
    assert any("acknowledgement write failed" in note for note in notes)
