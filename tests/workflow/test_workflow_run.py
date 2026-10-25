"""Focused tests of WorkflowRun, which executes one workflow invocation.

A run's single coordinator task starts a step task (named after its node) for
each ready node, commits finished steps in one write before their publications
become visible, and ends exactly when no step runs and no node is ready. These
tests drive it through public hooks only: tools, the event store, ``stop()``,
the caller's cancellation, and tasks found by name (the coordinator is named
after the workflow).
"""

import asyncio
import contextlib
import json
import re
import sys
import uuid
from typing import Any
from typing import AsyncIterator
from typing import Awaitable
from typing import Callable
from typing import Optional
from typing import Sequence

import pytest
from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.event_stores.event_store import EventStore
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.events.event import Event
from grafi.common.events.event_codec import default_event_codec
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
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.runtime import Delta
from grafi.runtime import GrafiRuntime
from grafi.runtime import emit_delta
from grafi.tools.tool import Tool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.expressions.topic_expression import SubExpr
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.impl.workflow_run import WorkflowRun
from tests_integration.async_execution.support import input_event

Script = Callable[[int, list[str]], AsyncIterator[Messages]]


class ScriptedTool(Tool):
    """Runs an async script per call: the tool's output is every message the
    script yields, once it ends."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    script: Any = Field(default=None, exclude=True)
    calls: list[list[str]] = Field(default_factory=list)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> Messages:
        contents = [str(message.content) for message in input_data]
        self.calls.append(contents)
        return [
            message
            async for batch in self.script(len(self.calls), contents)
            for message in batch
        ]


class Interrupt(BaseException):
    """Stands in for KeyboardInterrupt, which asyncio re-raises out of the loop."""


def reply(*texts: str) -> Messages:
    return [Message(role="assistant", content=text) for text in texts]


def emits(*texts: str) -> Script:
    async def script(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        for text in texts:
            yield reply(text)

    return script


async def echo(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
    yield reply("|".join(inputs))


def node(
    name: str, script: Script, source: TopicBase | SubExpr, *destinations: TopicBase
) -> Node:
    subscription = TopicExpr(topic=source) if isinstance(source, TopicBase) else source
    return Node(
        name=name,
        tool=ScriptedTool(script=script),
        subscribed_expressions=[subscription],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=destination) for destination in destinations]
        ),
    )


def workflow(*nodes: Node) -> EventDrivenWorkflow:
    builder = EventDrivenWorkflow.builder()
    for each in nodes:
        builder.node(each)
    return builder.build()


def calls(definition: EventDrivenWorkflow, name: str) -> list[list[str]]:
    tool = definition.nodes[name].tool
    assert isinstance(tool, ScriptedTool)
    return tool.calls


async def drain(
    definition: EventDrivenWorkflow,
    event: PublishToTopicEvent,
    sequential: bool = False,
) -> list[str]:
    async with asyncio.timeout(5):
        return [
            str(message.content)
            async for output in definition.invoke(event, sequential)
            for message in output.data
        ]


async def until(predicate: Callable[[], Any]) -> None:
    """Wait until ``predicate`` holds, polling for at most five seconds."""
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


def tasks_named(name: str) -> list["asyncio.Task[Any]"]:
    return [task for task in asyncio.all_tasks() if task.get_name() == name]


def publications(
    events: Sequence[Event], topic: Optional[str] = None
) -> list[PublishToTopicEvent]:
    return [
        event
        for event in events
        if isinstance(event, PublishToTopicEvent) and topic in (None, event.name)
    ]


def publishers(events: Sequence[Event]) -> set[str]:
    return {event.publisher_name for event in publications(events)}


class Writes:
    """The batches a run writes to the store, each recorded once written.

    ``before`` sees each batch first and may hold or fail the write.
    """

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        event_store: EventStore,
        before: Optional[Callable[[list[Event]], Awaitable[None]]] = None,
    ) -> None:
        self.batches: list[list[Event]] = []
        record_events = event_store.record_events

        async def record(events: Sequence[Event]) -> None:
            batch = list(events)
            if before is not None:
                await before(batch)
            await record_events(batch)
            self.batches.append(batch)

        monkeypatch.setattr(event_store, "record_events", record)

    def published(
        self, topic: Optional[str] = None, publisher: Optional[str] = None
    ) -> list[PublishToTopicEvent]:
        return [
            event
            for batch in self.batches
            for event in publications(batch, topic)
            if publisher in (None, event.publisher_name)
        ]


# --------------------------------------------------------------------------- #
# Readiness and termination
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize("send_b", [False, True])
async def test_and_join_ends_exactly_or_takes_both_topics_in_one_batch(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore, send_b: bool
) -> None:
    writes = Writes(monkeypatch, event_store)
    source, a, b = InputTopic(name="input"), Topic(name="a"), Topic(name="b")

    async def after_both_a(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await until(lambda: len(writes.published("a")) == 2)
        yield reply("B1")

    join = SubscriptionBuilder().subscribed_to(a).and_().subscribed_to(b).build()
    nodes = [
        node("a1", emits("A1"), source, a),
        node("a2", emits("A2"), source, a),
        node("join", echo, join, OutputTopic(name="out")),
    ]
    if send_b:
        nodes.append(node("b1", after_both_a, source, b))
    definition = workflow(*nodes)
    # Without B the run ends as soon as no step runs and no node is ready: it
    # has no idle period to wait out.
    async with asyncio.timeout(1):
        outputs = await drain(definition, input_event())
    if send_b:  # A1 and A2 were not taken as batches of their own.
        [batch] = calls(definition, "join")
        assert sorted(batch) == ["A1", "A2", "B1"]
        assert [sorted(output.split("|")) for output in outputs] == [sorted(batch)]
    else:
        assert outputs == [] and calls(definition, "join") == []
    assert not tasks_named(definition.name)


@pytest.mark.asyncio
async def test_or_join_runs_on_either_topic() -> None:
    a, b = InputTopic(name="a"), Topic(name="b")
    join = SubscriptionBuilder().subscribed_to(a).or_().subscribed_to(b).build()
    definition = workflow(node("join", echo, join, OutputTopic(name="out")))
    assert await drain(definition, input_event("A1")) == ["A1"]
    assert calls(definition, "join") == [["A1"]]


@pytest.mark.asyncio
async def test_a_node_runs_one_step_at_a_time_and_takes_what_arrived_meanwhile(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    writes = Writes(monkeypatch, event_store)
    first_started = asyncio.Event()
    running, peak = 0, 0

    async def worker(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        try:
            if call == 1:
                first_started.set()
                # x2 and x3 are committed while this step still runs.
                await until(lambda: len(writes.published("work")) == 3)
            yield reply("|".join(inputs))
        finally:
            running -= 1

    def after_first(text: str) -> Script:
        async def script(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
            await first_started.wait()
            yield reply(text)

        return script

    source, work = InputTopic(name="input"), Topic(name="work")
    definition = workflow(
        node("s1", emits("x1"), source, work),
        node("s2", after_first("x2"), source, work),
        node("s3", after_first("x3"), source, work),
        node("worker", worker, work, OutputTopic(name="out")),
    )
    await drain(definition, input_event())
    first, second = calls(definition, "worker")
    assert first == ["x1"] and sorted(second) == ["x2", "x3"]
    assert peak == 1


@pytest.mark.asyncio
async def test_steps_of_different_nodes_run_in_parallel() -> None:
    started = {"a": asyncio.Event(), "b": asyncio.Event()}

    def meets(me: str, other: str) -> Script:
        async def script(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
            started[me].set()
            await started[other].wait()  # Never returns unless both steps run.
            yield reply(me)

        return script

    source = InputTopic(name="input")
    definition = workflow(
        node("a", meets("a", "b"), source, OutputTopic(name="out_a")),
        node("b", meets("b", "a"), source, OutputTopic(name="out_b")),
    )
    assert sorted(await drain(definition, input_event())) == ["a", "b"]


@pytest.mark.asyncio
async def test_sequential_run_takes_one_step_at_a_time_in_ready_order() -> None:
    order: list[str] = []
    running, peak = 0, 0
    caller_has_a = asyncio.Event()

    def step(name: str) -> Script:
        async def script(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
            nonlocal running, peak
            order.append(name)
            running += 1
            peak = max(peak, running)
            try:
                if name == "b":
                    # Outputs reach the caller as each step commits.
                    await caller_has_a.wait()
                yield reply(name)
            finally:
                running -= 1

        return script

    source, mid = InputTopic(name="input"), Topic(name="mid")
    out = OutputTopic(name="out")
    definition = workflow(
        node("a", step("a"), source, out, mid),
        node("b", step("b"), source, out),
        node("c", step("c"), source, out),
        node("d", step("d"), mid, out),  # Ready only after a, so after b and c.
    )
    received: list[str] = []
    async with asyncio.timeout(5):
        async for output in definition.invoke(input_event(), True):
            received.append(str(output.data[0].content))
            caller_has_a.set()
    assert order == received == ["a", "b", "c", "d"]
    assert peak == 1


# --------------------------------------------------------------------------- #
# Commits
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_steps_finishing_together_commit_in_one_write(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    c_committing = asyncio.Event()

    async def before(batch: list[Event]) -> None:
        if "c" in publishers(batch):
            c_committing.set()
            # The coordinator is busy until a and b have both finished.
            await until(lambda: not tasks_named("a") and not tasks_named("b"))

    writes = Writes(monkeypatch, event_store, before)

    def after_c(*texts: str) -> Script:
        async def script(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
            await c_committing.wait()
            for text in texts:
                yield reply(text)

        return script

    source, mid = InputTopic(name="input"), Topic(name="mid")
    definition = workflow(
        node("c", emits("c"), source, OutputTopic(name="out_c")),
        node("a", after_c("a1", "a2"), source, mid),
        node("b", after_c("b1", "b2"), source, mid),
        node("sink", echo, mid, OutputTopic(name="out")),
    )
    await drain(definition, input_event())
    steps = [publishers(batch) & {"a", "b"} for batch in writes.batches]
    assert [step for step in steps if step] == [{"a", "b"}]
    # Concurrent producers get contiguous positions on their shared topic, and
    # the sink takes everything one commit published as one batch.
    assert sorted(event.offset for event in writes.published("mid")) == [0, 1]
    [batch] = calls(definition, "sink")
    assert sorted(batch) == ["a1", "a2", "b1", "b2"]


@pytest.mark.asyncio
async def test_downstream_never_reads_an_unstored_publication(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    sink_started = asyncio.Event()
    unstored: list[str] = []

    async def before(batch: list[Event]) -> None:
        if publications(batch, "mid"):
            # Hold the producer's write: a sink dispatched before the write
            # returns would start meanwhile.
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(0.05):
                    await sink_started.wait()

    writes = Writes(monkeypatch, event_store, before)

    async def sink(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        sink_started.set()
        stored = {
            str(message.content)
            for event in writes.published("mid")
            for message in event.data
        }
        unstored.extend(text for text in inputs if text not in stored)
        yield reply("|".join(inputs))

    source, mid = InputTopic(name="input"), Topic(name="mid")
    definition = workflow(
        node("producer", emits("x", "y"), source, mid),
        node("sink", sink, mid, OutputTopic(name="out")),
    )
    assert await drain(definition, input_event()) == ["x|y"]
    assert unstored == []


# --------------------------------------------------------------------------- #
# Failures
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_node_failure_raises_node_execution_error(sequential: bool) -> None:
    async def boom(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        raise RuntimeError("boom")
        yield reply("never")

    definition = workflow(
        node("node", boom, InputTopic(name="input"), OutputTopic(name="out"))
    )
    with pytest.raises(NodeExecutionError, match="boom") as raised:
        await drain(definition, input_event(), sequential)
    assert raised.value.node_name == "node"


@pytest.mark.asyncio
async def test_store_failure_while_starting_is_a_workflow_error() -> None:
    class BoomStore:
        async def get_agent_events(
            self, assistant_request_id: str, **kwargs: Any
        ) -> list[Event]:
            raise RuntimeError("store down")

    definition = workflow(
        node("node", echo, InputTopic(name="input"), OutputTopic(name="out"))
    )
    run = WorkflowRun(definition, BoomStore())
    with pytest.raises(WorkflowError) as raised:
        async for _ in run.run(input_event()):
            pass
    assert isinstance(raised.value.__cause__, RuntimeError)


@pytest.mark.asyncio
async def test_failure_stops_the_run_at_once_while_the_caller_is_paused() -> None:
    caller_has_output, cycling, stopped = (asyncio.Event() for _ in range(3))

    async def cycle(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        if call == 1:
            yield reply("tick")  # Makes this node ready again.
            return
        cycling.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopped.set()
            raise
        yield reply("never")

    async def fail(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await asyncio.gather(caller_has_output.wait(), cycling.wait())
        raise RuntimeError("failer failed")
        yield reply("never")

    source, tick = InputTopic(name="input"), Topic(name="tick")
    either = SubscriptionBuilder().subscribed_to(source).or_().subscribed_to(tick)
    definition = workflow(
        node("starter", emits("started"), source, OutputTopic(name="out")),
        node("cycler", cycle, either.build(), tick),
        node("failer", fail, source, OutputTopic(name="o2")),
    )
    outputs = definition.invoke(input_event())
    async with asyncio.timeout(5):
        assert (await anext(outputs)).data[0].content == "started"
        caller_has_output.set()
        await stopped.wait()  # The caller is paused, yet the run stopped its step.
        with pytest.raises(NodeExecutionError, match="failer failed"):
            await outputs.aclose()
    assert len(calls(definition, "cycler")) == 2  # And started no other.


@pytest.mark.asyncio
async def test_first_failure_is_raised_and_later_ones_are_noted(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    async def fail_acknowledgement(batch: list[Event]) -> None:
        if any(isinstance(event, ConsumeFromTopicEvent) for event in batch) and all(
            getattr(event, "consumer_name", None) == "EventDrivenWorkflow"
            for event in batch
        ):
            raise OSError("acknowledgement failed")

    Writes(monkeypatch, event_store, fail_acknowledgement)
    received = asyncio.Event()

    async def fail(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await received.wait()
        raise RuntimeError("node failed")
        yield reply("never")

    # Two producers, so the output reaches the caller only once it is stored,
    # and the close then acknowledges it.
    source, out = InputTopic(name="input"), OutputTopic(name="out")
    definition = workflow(
        node("emit", emits("first"), source, out),
        node("fail", fail, source, out),
    )
    with pytest.raises(NodeExecutionError, match="node failed") as raised:
        async with asyncio.timeout(5):
            async for _ in definition.invoke(input_event()):
                received.set()
    notes = getattr(raised.value, "__notes__", [])
    assert any(
        "Later failure" in note and "acknowledgement failed" in note for note in notes
    )


@pytest.mark.asyncio
async def test_a_failure_cancels_the_other_steps_at_once() -> None:
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def wait(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise ConnectionError("transport closed")  # Reports the cancel.
        yield reply("never")

    async def fail(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await started.wait()
        raise RuntimeError("node failed")
        yield reply("never")

    source = InputTopic(name="input")
    definition = workflow(
        node("waits", wait, source, OutputTopic(name="out")),
        node("fails", fail, source, Topic(name="side")),
    )
    with pytest.raises(NodeExecutionError, match="node failed") as raised:
        await drain(definition, input_event())
    assert cancelled.is_set()
    # The cancelled step's error is a consequence of the stop, not a failure.
    notes = getattr(raised.value, "__notes__", [])
    assert not any("transport closed" in note for note in notes)


@pytest.mark.asyncio
async def test_a_step_finishing_with_a_failed_one_is_still_committed(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    committing = asyncio.Event()

    async def before(batch: list[Event]) -> None:
        if "first" in publishers(batch):
            # While the run commits "first", "ok" and then "bad" finish, so
            # they are settled together, the successful one first.
            committing.set()
            await until(lambda: not tasks_named("ok") and not tasks_named("bad"))
            await asyncio.sleep(0)  # Their done callbacks queue them.

    writes = Writes(monkeypatch, event_store, before)

    async def succeed(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await committing.wait()
        yield reply("kept")

    async def fail(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await committing.wait()
        await until(lambda: not tasks_named("ok"))
        raise RuntimeError("bad failed")
        yield reply("never")

    source = InputTopic(name="input")
    definition = workflow(
        node("first", emits("early"), source, Topic(name="early")),
        node("ok", succeed, source, Topic(name="kept")),
        node("bad", fail, source, OutputTopic(name="out")),
    )
    with pytest.raises(NodeExecutionError, match="bad failed"):
        await drain(definition, input_event())
    # The successful step is stored, so it does not run again on resume.
    assert writes.published("kept")


@pytest.mark.asyncio
async def test_a_runs_failure_does_not_replace_the_callers_interrupt(
    event_store: EventStore,
) -> None:
    received = asyncio.Event()

    async def fail(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await received.wait()
        raise RuntimeError("node failed")
        yield reply("never")

    source = InputTopic(name="input")
    definition = workflow(
        node("emits", emits("first"), source, OutputTopic(name="out")),
        node("fails", fail, source, Topic(name="side")),
    )
    run = WorkflowRun(definition, event_store)
    outputs = run.run(input_event())
    async with asyncio.timeout(5):
        await anext(outputs)
        received.set()
        await until(lambda: run._failure is not None)
        # The caller is interrupted while holding the output.
        with pytest.raises(Interrupt) as raised:
            await outputs.athrow(Interrupt("interrupted"))
    assert any("node failed" in note for note in raised.value.__notes__)


@pytest.mark.asyncio
async def test_interrupt_outranks_a_failure() -> None:
    slow_started = asyncio.Event()

    async def fail(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await slow_started.wait()
        raise RuntimeError("node failed")
        yield reply("never")

    async def slow(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        slow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise Interrupt("interrupted while stopping")
        yield reply("never")

    source = InputTopic(name="input")
    definition = workflow(
        node("fail", fail, source, OutputTopic(name="o1")),
        node("slow", slow, source, OutputTopic(name="o2")),
    )
    with pytest.raises(Interrupt) as raised:
        await drain(definition, input_event())
    notes = getattr(raised.value, "__notes__", [])
    assert any("Workflow failure" in note and "node failed" in note for note in notes)


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_step_cancelled_from_outside_fails_the_run(sequential: bool) -> None:
    started = asyncio.Event()

    async def slow(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        started.set()
        await asyncio.Event().wait()
        yield reply("never")

    definition = workflow(
        node("slow", slow, InputTopic(name="input"), OutputTopic(name="out"))
    )

    async def cancel_the_step() -> None:
        await started.wait()
        [task] = tasks_named("slow")
        task.cancel("pool shutdown")

    canceller = asyncio.create_task(cancel_the_step())
    with pytest.raises(NodeExecutionError) as raised:
        await drain(definition, input_event(), sequential)
    await canceller
    assert raised.value.node_name == "slow"
    # Who cancelled it, and why, stays in the chain.
    failure = raised.value.__cause__
    assert isinstance(failure, RuntimeError)
    assert str(failure) == "Node execution was unexpectedly cancelled"
    assert isinstance(failure.__cause__, asyncio.CancelledError)
    assert failure.__cause__.args == ("pool shutdown",)


# --------------------------------------------------------------------------- #
# Stopping and closing
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_stop_commits_finished_steps_and_only_logs_stopped_steps_errors(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    c_committing, release, slow_started = (asyncio.Event() for _ in range(3))

    async def before(batch: list[Event]) -> None:
        if "c" in publishers(batch):
            c_committing.set()
            await release.wait()  # The coordinator is busy while "done" ends.

    writes = Writes(monkeypatch, event_store, before)

    async def done(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await c_committing.wait()
        yield reply("done")

    async def slow(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        slow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise ConnectionError("transport closed")  # Reports the stop.
        yield reply("never")

    source = InputTopic(name="input")
    definition = workflow(
        node("c", emits("c"), source, OutputTopic(name="out_c")),
        node("done", done, source, OutputTopic(name="out_done")),
        node("slow", slow, source, OutputTopic(name="out_slow")),
    )
    messages: list[str] = []
    handler = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        draining = asyncio.create_task(drain(definition, input_event()))
        async with asyncio.timeout(5):
            await asyncio.gather(c_committing.wait(), slow_started.wait())
            await until(lambda: not tasks_named("done"))  # Finished, not committed.
            definition.stop()
            release.set()
            outputs = await draining
    finally:
        logger.remove(handler)
    assert sorted(outputs) == ["c", "done"]  # The stop is not a failure.
    assert writes.published(publisher="done")
    assert any(
        isinstance(event, ConsumeFromTopicEvent) and event.consumer_name == "done"
        for batch in writes.batches
        for event in batch
    )
    assert not writes.published(publisher="slow")
    assert any("Not raised" in m and "transport closed" in m for m in messages)


@pytest.mark.asyncio
async def test_stop_from_another_thread_ends_the_run() -> None:
    started, closed = asyncio.Event(), asyncio.Event()

    async def waits(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        try:
            started.set()
            await asyncio.Event().wait()
            yield reply("never")
        finally:
            closed.set()

    definition = workflow(
        node("waiter", waits, InputTopic(name="input"), OutputTopic(name="out"))
    )

    async def run() -> list[ConsumeFromTopicEvent]:
        assistant = Assistant(workflow=definition)
        return [
            output async for output in GrafiRuntime().invoke(assistant, input_event())
        ]

    task = asyncio.create_task(run())
    try:
        async with asyncio.timeout(5):
            await started.wait()
            await asyncio.to_thread(definition.stop)
            assert await task == []
        assert closed.is_set()
        assert not definition._active_runs
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_stop_forwards_to_active_runs() -> None:
    definition = workflow(
        node("node", echo, InputTopic(name="input"), OutputTopic(name="out"))
    )
    run = WorkflowRun(definition, EventStoreInMemory())
    definition._active_runs[id(run)] = run
    definition.stop()

    async def outputs() -> list[ConsumeFromTopicEvent]:
        return [output async for output in run.run(input_event())]

    # Stopped before it started, the run takes no step.
    assert asyncio.run(outputs()) == []
    assert calls(definition, "node") == []


@pytest.mark.asyncio
async def test_active_runs_are_cleared_after_invoke() -> None:
    definition = workflow(
        node("node", echo, InputTopic(name="input"), OutputTopic(name="out"))
    )
    assert await drain(definition, input_event("hi")) == ["hi"]
    assert definition._active_runs == {}


@pytest.mark.asyncio
async def test_timeout_around_the_close_bounds_it_when_a_step_ignores_cancel() -> None:
    stopping = asyncio.Event()

    async def stubborn(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        emit_delta("a")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopping.set()
            await asyncio.Event().wait()  # Ignores the first cancellation.
        yield reply("never")

    definition = workflow(
        node("stubborn", stubborn, InputTopic(name="input"), OutputTopic(name="out"))
    )
    outputs = definition.invoke(input_event(), stream=True)
    async with asyncio.timeout(5):
        assert await anext(outputs) == Delta("a", "stubborn", 1)
        closing = asyncio.create_task(outputs.aclose())
        await stopping.wait()  # The close waits for a step that will not end.
        closing.cancel()  # A timeout around the close.
        await asyncio.wait({closing})
    assert closing.cancelled()
    # The run cancelled the step again and waited for it before the close ended.
    assert not tasks_named("stubborn") and not tasks_named(definition.name)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["running", "finished"])
async def test_coordinator_cancelled_from_outside_ends_without_the_close(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore, stage: str
) -> None:
    # Regression: a coordinator cancelled by someone else (asyncio.run()
    # cancels leftover tasks at shutdown) must not wait for the caller to close
    # the stream, which may never happen.
    writes = Writes(monkeypatch, event_store)

    async def emit(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        if stage == "running":
            emit_delta("a")
            await asyncio.Event().wait()
        yield reply("a")

    definition = workflow(
        node("emit", emit, InputTopic(name="input"), OutputTopic(name="out"))
    )
    event = input_event()
    outputs = definition.invoke(event, stream=True)
    async with asyncio.timeout(5):
        first = await anext(outputs)
        if stage == "running":  # Streamed by the step, which is still running.
            assert first == Delta("a", "emit", 1)
        else:
            assert not isinstance(first, Delta) and first.data[0].content == "a"
        if stage == "finished":  # Nothing is left to run; the run awaits the close.
            await until(lambda: writes.published("out"))
        [coordinator] = tasks_named(definition.name)
        coordinator.cancel("loop shutdown")
        await asyncio.wait({coordinator})  # The caller has not closed the stream.
        assert not tasks_named("emit")
        with pytest.raises(WorkflowError, match="unexpectedly cancelled") as raised:
            await anext(outputs)
    cancellation = raised.value.__cause__.__cause__
    assert isinstance(cancellation, asyncio.CancelledError)
    assert cancellation.args == ("loop shutdown",)
    if stage == "finished":  # Never acknowledged, so delivered again.
        assert await drain(definition, event) == ["a"]


@pytest.mark.asyncio
async def test_coordinator_cancelled_from_outside_while_steps_stop_ends_at_once() -> (
    None
):
    # Regression: an outside cancellation that lands while the run waits for a
    # step to stop still ends the run without waiting for the caller's close.
    received, stopping = asyncio.Event(), asyncio.Event()

    async def slow_to_stop(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        emit_delta("a")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopping.set()
            await asyncio.Event().wait()  # Stops when cancelled again.
        yield reply("never")

    async def fail(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await received.wait()
        raise RuntimeError("node failed")
        yield reply("never")

    source = InputTopic(name="input")
    definition = workflow(
        node("slow", slow_to_stop, source, OutputTopic(name="out")),
        node("fails", fail, source, Topic(name="side")),
    )
    outputs = definition.invoke(input_event(), stream=True)
    async with asyncio.timeout(5):
        await anext(outputs)
        received.set()
        await stopping.wait()
        [coordinator] = tasks_named(definition.name)
        coordinator.cancel("loop shutdown")
        await asyncio.wait({coordinator})  # The caller has not closed the stream.
        assert not tasks_named("slow")
        with pytest.raises(NodeExecutionError, match="node failed"):
            await anext(outputs)


@pytest.mark.asyncio
async def test_no_step_is_committed_after_a_write_that_may_have_landed(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    # Regression: a write can fail after it landed (a connection lost during
    # COMMIT). Committing another step afterwards would reuse its positions.
    writing = asyncio.Event()
    record_events = event_store.record_events

    async def lands_then_fails(events: Sequence[Event]) -> None:
        await record_events(events)
        if "fast" in publishers(list(events)):
            writing.set()
            await until(lambda: not tasks_named("slow"))
            await asyncio.sleep(0)  # Its done callback queues it.
            raise OSError("connection lost during commit")

    monkeypatch.setattr(event_store, "record_events", lands_then_fails)

    async def slow(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await writing.wait()
        yield reply("slow")

    source, mid = InputTopic(name="input"), Topic(name="mid")
    definition = workflow(
        node("fast", emits("fast"), source, mid),
        node("slow", slow, source, mid),
        node("sink", echo, mid, OutputTopic(name="out")),
    )
    event = input_event()
    with pytest.raises(WorkflowError, match="execution failed"):
        await drain(definition, event)
    history = await event_store.get_agent_events(
        event.invoke_context.assistant_request_id
    )
    positions = [p.offset for p in publications(history, "mid")]
    assert positions == [0]  # Only the write that landed.
    monkeypatch.setattr(event_store, "record_events", record_events)
    assert sorted(await drain(definition, event)) == ["fast", "slow"]


@pytest.mark.asyncio
async def test_sequential_run_takes_the_first_ready_node_first() -> None:
    order: list[str] = []

    def tracked(name: str) -> Script:
        async def script(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
            order.append(name)
            yield reply(name)

        return script

    source, x_out, y_out = InputTopic(name="input"), Topic(name="x"), Topic(name="y")
    definition = workflow(
        node("X", tracked("X"), source, x_out),
        node("Y", tracked("Y"), source, y_out),
        node("Z2", tracked("Z2"), y_out, OutputTopic(name="out")),
        node("Z1", tracked("Z1"), x_out, OutputTopic(name="out")),
    )
    await drain(definition, input_event(), sequential=True)
    # Z1 became ready (after X) before Z2 (after Y), whatever the definition
    # order.
    assert order == ["X", "Y", "Z1", "Z2"]


def test_system_exit_in_the_coordinator_leaves_the_loop() -> None:
    # As asyncio does for any task: an exit raised by a store is not held until
    # the stream is closed, which an abandoned stream never is.
    from grafi.runtime.execution_services import ExecutionServices
    from grafi.runtime.execution_services import bind_services

    class ExitingStore(EventStoreInMemory):
        async def record_events(self, events: Sequence[Event]) -> None:
            if any(isinstance(e, ConsumeFromTopicEvent) for e in events):
                raise SystemExit("store shut down")
            await super().record_events(events)

    definition = workflow(
        node("emit", emits("a"), InputTopic(name="input"), OutputTopic(name="out"))
    )

    async def main() -> None:
        with bind_services(ExecutionServices(event_store=ExitingStore())):
            outputs = definition.invoke(input_event())
            await anext(outputs)  # Streamed; the step's commit then exits.
            await asyncio.sleep(0.1)  # The stream is left open.

    with pytest.raises(SystemExit):
        asyncio.run(main())


def test_an_exit_in_the_coordinator_fails_the_run_for_its_caller() -> None:
    # Regression: an exit raised in the coordinator's own code (here a commit)
    # was not recorded as the run's failure: the other step kept running and,
    # on a loop that keeps running after the exit, the caller saw the stream
    # end as if the run had succeeded. The other step's own error as it stops
    # is logged, as for any stopping step, not left unretrieved.
    import gc

    from grafi.runtime.execution_services import ExecutionServices
    from grafi.runtime.execution_services import bind_services

    class ExitingStore(EventStoreInMemory):
        async def record_events(self, events: Sequence[Event]) -> None:
            if any(isinstance(e, ConsumeFromTopicEvent) for e in events):
                raise SystemExit("store shut down")
            await super().record_events(events)

    async def slow(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise OSError("transport reports the cancellation")
        yield reply("late")

    source = InputTopic(name="input")
    definition = workflow(
        node("fast", emits("a"), source, Topic(name="side")),
        node("slow", slow, source, OutputTopic(name="out")),
    )

    async def read() -> list[Any]:
        return [o async for o in definition.invoke(input_event())]

    logged: list[dict[str, Any]] = []
    messages: list[str] = []
    handler = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    loop = asyncio.new_event_loop()
    loop.set_exception_handler(lambda loop, context: logged.append(context))
    try:
        with bind_services(ExecutionServices(event_store=ExitingStore())):
            reader = loop.create_task(read())
            with pytest.raises(SystemExit):  # It leaves the loop once.
                loop.run_until_complete(reader)
            assert not reader.done()  # Not through the caller's own task.
            with pytest.raises(WorkflowError, match="interrupted") as raised:
                loop.run_until_complete(reader)  # The loop keeps running.
        assert isinstance(raised.value.__cause__, SystemExit)
        assert all(task.done() for task in asyncio.all_tasks(loop))
    finally:
        loop.close()
        logger.remove(handler)
    del raised, reader
    gc.collect()
    assert any("node 'slow' was stopping" in message for message in messages)
    assert logged == []


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="eager task factories need Python 3.12"
)
def test_the_coordinator_does_not_start_in_the_callers_frame() -> None:
    # Regression: under an eager task factory the coordinator ran its first
    # step (here the history load) in the caller's frame, so an exit there
    # escaped through the caller as is, skipping the close.
    from grafi.runtime.execution_services import ExecutionServices
    from grafi.runtime.execution_services import bind_services

    class ExitingStore(EventStoreInMemory):
        async def get_agent_events(
            self, assistant_request_id: str, **kwargs: Any
        ) -> list[Event]:
            raise SystemExit("store shut down")

    definition = workflow(
        node("emit", emits("a"), InputTopic(name="input"), OutputTopic(name="out"))
    )

    async def read() -> list[Any]:
        return [o async for o in definition.invoke(input_event())]

    def scenario() -> None:
        loop = asyncio.new_event_loop()
        loop.set_task_factory(asyncio.eager_task_factory)  # type: ignore[attr-defined]
        try:
            with bind_services(ExecutionServices(event_store=ExitingStore())):
                reader = loop.create_task(read())
                with pytest.raises(SystemExit):  # From the coordinator, once.
                    loop.run_until_complete(reader)
                assert not reader.done()  # Not through the caller's own task.
                with pytest.raises(WorkflowError, match="interrupted"):
                    loop.run_until_complete(reader)
        finally:
            loop.close()

    # In a thread of its own, so that a regression fails rather than hangs.
    outcome: list[Optional[BaseException]] = []

    def run_scenario() -> None:
        try:
            scenario()
            outcome.append(None)
        except BaseException as error:
            outcome.append(error)

    import threading

    thread = threading.Thread(target=run_scenario, daemon=True)
    thread.start()
    thread.join(10)
    assert outcome, "the run did not finish"
    if outcome[0] is not None:
        raise outcome[0]


def test_stop_from_a_signal_handler_interrupting_the_lock_does_not_deadlock(
    event_store: EventStore,
) -> None:
    # Regression: a signal handler runs in the main thread between bytecodes,
    # so stop() from one could interrupt code holding the run's lock and wait
    # for it forever.
    import threading

    definition = workflow(
        node("emit", emits("a"), InputTopic(name="input"), OutputTopic(name="out"))
    )
    run = WorkflowRun(definition, event_store)
    stopped = threading.Event()

    def interrupted_while_holding_the_lock() -> None:
        with run._loop_lock:
            run.stop()  # As a signal handler landing here would.
        stopped.set()

    thread = threading.Thread(target=interrupted_while_holding_the_lock, daemon=True)
    thread.start()
    thread.join(5)
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_a_reader_cancelled_again_while_closing_logs_no_warning(
    event_store: EventStore,
) -> None:
    # Regression: anyio cancel scopes cancel every await again, so a reader's
    # close was cancelled a second time, and that second cancellation was noted
    # on the first with a warning and a traceback on every disconnect.
    started = asyncio.Event()

    async def slow_to_stop(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        yield reply("first")
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0.05)  # Its cleanup takes a while.

    definition = workflow(
        node("n", slow_to_stop, InputTopic(name="input"), OutputTopic(name="out"))
    )

    async def read() -> None:
        async for _ in definition.invoke(input_event()):
            pass

    messages: list[str] = []
    handler = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        reader = asyncio.create_task(read())
        async with asyncio.timeout(5):
            await started.wait()
            reader.cancel()  # While it waits for the next output.
            await asyncio.sleep(0.01)  # It is now closing.
            reader.cancel()  # Cancelled again, as an anyio scope does.
            await asyncio.wait({reader})
    finally:
        logger.remove(handler)
    assert reader.cancelled()
    assert not [message for message in messages if "Also raised" in message]


def test_an_exit_from_a_store_write_lets_the_loop_runner_clean_up() -> None:
    # Regression: an assistant's or workflow's event is written in a task of
    # its own; an exit raised there left the loop, and the caller raised it
    # again as asyncio.run() cancelled it, cutting that cleanup short.
    from grafi.common.events.component_base import InvokeEvent
    from grafi.runtime.execution_services import ExecutionServices
    from grafi.runtime.execution_services import bind_services

    started = asyncio.Event()

    async def slow(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        started.set()
        await asyncio.sleep(10)
        yield reply("late")

    definition = workflow(
        node("slow", slow, InputTopic(name="input"), OutputTopic(name="out"))
    )
    exiting = input_event("exit")

    class ExitingStore(EventStoreInMemory):
        async def record_event(self, event: Event) -> None:
            if isinstance(event, InvokeEvent) and event.invoke_context == (
                exiting.invoke_context
            ):
                raise SystemExit("store shut down")
            await super().record_event(event)

    loops: list[asyncio.AbstractEventLoop] = []

    async def read(event: PublishToTopicEvent) -> None:
        async for _ in definition.invoke(event):
            pass

    async def main() -> None:
        loops.append(asyncio.get_running_loop())
        with bind_services(ExecutionServices(event_store=ExitingStore())):
            async with asyncio.TaskGroup() as group:
                group.create_task(read(input_event("stay")))
                await started.wait()
                group.create_task(read(exiting))

    with pytest.raises(SystemExit, match="store shut down"):
        asyncio.run(main())
    assert [task for task in asyncio.all_tasks(loops[0]) if not task.done()] == []


def test_an_exit_reaching_a_stream_left_open_lets_the_loop_runner_clean_up() -> None:
    # Regression: a caller cancelled in its own loop body leaves the stream
    # open; the loop's shutdown then closes it from another task, which raised
    # the run's exit again and cut the cleanup short.
    async def script(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        yield reply("first")
        await asyncio.sleep(0.02)
        if inputs == ["exit"]:
            raise SystemExit("tool called sys.exit()")
        await asyncio.sleep(10)

    definition = workflow(
        node("n", script, InputTopic(name="input"), OutputTopic(name="out"))
    )
    loops: list[asyncio.AbstractEventLoop] = []

    async def read(content: str) -> None:
        async for _ in definition.invoke(input_event(content)):
            await asyncio.sleep(10)  # Busy in its own code when cancelled.

    async def main() -> None:
        loops.append(asyncio.get_running_loop())
        async with asyncio.TaskGroup() as group:
            group.create_task(read("exit"))
            group.create_task(read("stay"))

    with pytest.raises(SystemExit, match="tool called sys.exit"):
        asyncio.run(main())
    assert [task for task in asyncio.all_tasks(loops[0]) if not task.done()] == []


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="eager task factories need Python 3.12"
)
def test_an_exit_under_an_eager_task_factory_leaves_the_loop_from_its_task() -> None:
    # Regression: under an eager task factory a step ran its first part in the
    # coordinator's frame, and the coordinator in the caller's: a tool's exit
    # raised before its first await escaped through them, skipping the close,
    # reaching the caller as is, and leaving exceptions never retrieved.
    import gc

    async def exits(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        raise SystemExit("tool exits at once")
        yield reply("never")

    async def slow(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await asyncio.sleep(10)
        yield reply("late")

    source = InputTopic(name="input")
    definition = workflow(
        node("exits", exits, source, Topic(name="side")),
        node("slow", slow, source, OutputTopic(name="out")),
    )

    async def read() -> list[Any]:
        return [o async for o in definition.invoke(input_event())]

    logged: list[dict[str, Any]] = []
    loop = asyncio.new_event_loop()
    loop.set_task_factory(asyncio.eager_task_factory)  # type: ignore[attr-defined]
    loop.set_exception_handler(lambda loop, context: logged.append(context))
    try:
        reader = loop.create_task(read())
        with pytest.raises(SystemExit):  # From the step's task, once.
            loop.run_until_complete(reader)
        assert not reader.done()  # Not through the caller's own task.
        with pytest.raises(WorkflowError, match="interrupted"):
            loop.run_until_complete(reader)  # The loop keeps running.
        assert all(task.done() for task in asyncio.all_tasks(loop))
    finally:
        loop.close()
    del reader
    gc.collect()
    assert logged == []


@pytest.mark.asyncio
async def test_stop_during_the_workflows_first_write_stops_the_run(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    # Regression: the run is registered before the workflow's invoke event is
    # written, so a stop that arrives during that write still reaches it.
    writing = asyncio.Event()
    record_event = event_store.record_event

    async def slow_record_event(event: Event) -> None:
        writing.set()
        await asyncio.sleep(0.01)
        await record_event(event)

    monkeypatch.setattr(event_store, "record_event", slow_record_event)
    definition = workflow(
        node("emit", emits("ran"), InputTopic(name="input"), OutputTopic(name="out"))
    )

    async def consume() -> list[str]:
        return await drain(definition, input_event())

    consumer = asyncio.create_task(consume())
    await writing.wait()
    definition.stop()
    assert await consumer == []
    assert calls(definition, "emit") == []


@pytest.mark.asyncio
async def test_closing_while_the_caller_is_cancelled_keeps_its_cancellation(
    event_store: EventStore,
) -> None:
    from contextlib import aclosing

    received = asyncio.Event()

    async def fail(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await received.wait()
        raise RuntimeError("node failed")
        yield reply("never")

    source = InputTopic(name="input")
    definition = workflow(
        node("emits", emits("first"), source, OutputTopic(name="out")),
        node("fails", fail, source, Topic(name="side")),
    )
    run = WorkflowRun(definition, event_store)

    async def consume() -> None:
        async with aclosing(run.run(input_event())) as outputs:
            async for _ in outputs:
                received.set()
                await asyncio.Event().wait()  # Busy when it is cancelled.

    consumer = asyncio.create_task(consume())
    await until(lambda: run._failure is not None)
    consumer.cancel()
    # The close (GeneratorExit while cancelling) logs the failure rather than
    # replacing the caller's cancellation.
    with pytest.raises(asyncio.CancelledError):
        await consumer


@pytest.mark.asyncio
async def test_a_failed_steps_cleanup_is_not_cut_short_when_the_caller_sees_it(
    event_store: EventStore,
) -> None:
    # Regression: the caller noticing the run's failure must not cancel the
    # failed step's cleanup; only a caller that leaves early does.
    received = asyncio.Event()
    cleanup: list[str] = []

    class Rejecting(Topic):
        def prepare_publication(
            self, publish_event: PublishToTopicEvent
        ) -> PublishToTopicEvent:
            raise ValueError("invalid publication")

    class Bad(Node):
        """A node whose stream cleans up as it is closed."""

        async def invoke(
            self, invoke_context: InvokeContext, node_input: list[Any]
        ) -> AsyncIterator[PublishToTopicEvent]:
            await received.wait()
            try:
                async for publication in super().invoke(invoke_context, node_input):
                    yield publication
            finally:
                try:
                    await asyncio.sleep(0.05)  # Releasing a client, say.
                    cleanup.append("closed")
                except asyncio.CancelledError:
                    cleanup.append("cancelled")
                    raise

    source = InputTopic(name="input")
    bad = Bad(
        name="bad",
        tool=ScriptedTool(script=emits("x")),
        subscribed_expressions=[TopicExpr(topic=source)],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=Rejecting(name="mid"))]
        ),
    )
    definition = workflow(
        node("early", emits("first"), source, OutputTopic(name="out")), bad
    )
    outputs = definition.invoke(input_event())
    async with asyncio.timeout(5):
        await anext(outputs)
        received.set()
        await until(
            lambda: any(run._failure for run in definition._active_runs.values())
        )
        with pytest.raises(NodeExecutionError, match="invalid publication"):
            await anext(outputs)  # The caller sees the failure while bad closes.
    assert cleanup == ["closed"]


@pytest.mark.asyncio
async def test_a_stopped_step_that_returns_is_not_committed(
    event_store: EventStore,
) -> None:
    # Regression: a step that absorbs the stop's cancellation and returns may
    # have cut its work short, so it runs again on resume instead.
    started = asyncio.Event()

    async def partial(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        if call > 1:
            yield reply("part1", "part2")
            return
        yield reply("part1")
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return  # Swallows the stop and returns early.
        yield reply("part2")

    source, mid = InputTopic(name="input"), Topic(name="mid")
    definition = workflow(
        node("s", partial, source, mid),
        node("sink", echo, mid, OutputTopic(name="out")),
    )
    event = input_event()
    outputs = definition.invoke(event)
    consumer = asyncio.create_task(anext(outputs))
    async with asyncio.timeout(5):
        await started.wait()
        definition.stop()
        with pytest.raises(StopAsyncIteration):
            await consumer
    history = await event_store.get_agent_events(
        event.invoke_context.assistant_request_id
    )
    assert not publications(history, "mid")
    # On resume the step runs again, whole.
    assert await drain(definition, event) == ["part1|part2"]


@pytest.mark.asyncio
async def test_a_step_that_asks_to_stop_finishes(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    # A "finish" tool that stops the workflow still delivers its own output
    # and is stored, so a resume does not run it (and stop) again; the other
    # steps are cancelled.
    writes = Writes(monkeypatch, event_store)
    definitions: list[EventDrivenWorkflow] = []
    other_cancelled = asyncio.Event()

    async def finish(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        definitions[0].stop()
        await asyncio.sleep(0)
        yield reply("final answer")

    async def other(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        if call == 1:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                other_cancelled.set()
                raise
        yield reply("side")

    source = InputTopic(name="input")
    definition = workflow(
        node("other", other, source, Topic(name="side")),
        node("finish", finish, source, OutputTopic(name="out")),
    )
    definitions.append(definition)
    event = input_event()
    assert await drain(definition, event) == ["final answer"]
    assert other_cancelled.is_set()
    assert writes.published("out", publisher="finish")
    # On resume only the cancelled step runs again; "finish" does not.
    assert await drain(definition, event) == []
    assert len(calls(definition, "finish")) == 1
    assert len(calls(definition, "other")) == 2


@pytest.mark.asyncio
async def test_unacknowledged_outputs_are_delivered_again_in_history_order(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    # Regression: redelivered in the order they were stored, not grouped by
    # topic (here "z_out" is registered before "a_out" but published after).
    a_stored = asyncio.Event()
    record_events = event_store.record_events

    async def record(events: Sequence[Event]) -> None:
        if any(isinstance(e, ConsumeFromTopicEvent) for e in events) and all(
            getattr(e, "consumer_name", None) == "EventDrivenWorkflow" for e in events
        ):
            raise OSError("acknowledgement failed")
        await record_events(events)
        if any(
            isinstance(e, PublishToTopicEvent) and e.name == "a_out" for e in events
        ):
            a_stored.set()

    monkeypatch.setattr(event_store, "record_events", record)

    async def later(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await a_stored.wait()
        yield reply("second")

    source = InputTopic(name="input")
    definition = workflow(
        node("late", later, source, OutputTopic(name="z_out")),
        node("early", emits("first"), source, OutputTopic(name="a_out")),
    )
    event = input_event()
    with pytest.raises(WorkflowError, match="execution failed"):
        await drain(definition, event)  # Delivered, but never acknowledged.
    monkeypatch.setattr(event_store, "record_events", record_events)
    assert await drain(definition, event) == ["first", "second"]


@pytest.mark.asyncio
async def test_outputs_of_one_topic_are_delivered_again_in_position_order(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    # Regression: an acknowledgement covers every earlier position of its
    # topic, so redelivering a later position first would lose the earlier
    # one. The store returns history by timestamp, as EventStorePostgres does.
    get_agent_events = event_store.get_agent_events

    async def by_timestamp(assistant_request_id: str, **kwargs: Any) -> list[Event]:
        events = await get_agent_events(assistant_request_id, **kwargs)
        return sorted(events, key=lambda event: event.timestamp)

    monkeypatch.setattr(event_store, "get_agent_events", by_timestamp)
    record_events = event_store.record_events
    p1_yielded, p2_stored = asyncio.Event(), asyncio.Event()

    async def fail_acknowledgement(events: Sequence[Event]) -> None:
        if all(
            getattr(e, "consumer_name", None) == "EventDrivenWorkflow" for e in events
        ):
            raise OSError("acknowledgement failed")
        await record_events(events)
        if "p2" in publishers(list(events)):
            p2_stored.set()

    async def p1(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        yield reply("p1")  # Made first, so its timestamp is earlier ...
        p1_yielded.set()
        await p2_stored.wait()  # ... but committed second, at position 1.

    async def p2(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await p1_yielded.wait()
        yield reply("p2")

    source, out = InputTopic(name="input"), OutputTopic(name="out")
    definition = workflow(node("p1", p1, source, out), node("p2", p2, source, out))
    event = input_event()
    monkeypatch.setattr(event_store, "record_events", fail_acknowledgement)
    with pytest.raises(WorkflowError, match="execution failed"):
        await drain(definition, event)  # Delivered, never acknowledged.
    monkeypatch.setattr(event_store, "record_events", record_events)
    outputs = definition.invoke(event)
    async with asyncio.timeout(5):
        first = await anext(outputs)
        await outputs.aclose()  # Acknowledges the one output handed over.
    assert first.data[0].content == "p2"  # Position 0 first.
    assert await drain(definition, event) == ["p1"]


@pytest.mark.asyncio
async def test_a_topic_keeps_only_what_its_readers_have_not_taken(
    event_store: EventStore,
) -> None:
    source, mid = InputTopic(name="input"), Topic(name="mid")
    definition = workflow(
        node("a", emits("1", "2"), source, mid),
        node("b", echo, mid, OutputTopic(name="out")),
        node("c", echo, mid, OutputTopic(name="out")),
    )
    run = WorkflowRun(definition, event_store)
    async with asyncio.timeout(5):
        outputs = [o async for o in run.run(input_event())]
    assert len(outputs) == 2
    log = run._topics["mid"]
    assert (log.start, log.size, log.events) == (1, 1, [])  # Both readers took it.
    assert run._topics["out"].events == []  # Read by the caller, not by a node.


@pytest.mark.asyncio
async def test_a_topic_keeps_what_a_reader_has_not_taken(
    event_store: EventStore,
) -> None:
    source, mid = InputTopic(name="input"), Topic(name="mid")
    never = Topic(name="never")  # Nothing publishes to it.
    definition = workflow(
        node("a", emits("1", "2"), source, mid),
        node("b", echo, mid, OutputTopic(name="out")),
        node(
            "c",
            echo,
            SubscriptionBuilder()
            .subscribed_to(mid)
            .and_()
            .subscribed_to(never)
            .build(),
            OutputTopic(name="out"),
        ),
    )
    run = WorkflowRun(definition, event_store)
    async with asyncio.timeout(5):
        outputs = [o.data[0].content async for o in run.run(input_event())]
    assert outputs == ["1|2"]
    log = run._topics["mid"]
    assert log.next_position == {"b": 1}
    # b took it, but c has not: it is kept for c.
    assert (log.start, log.size) == (0, 1)
    assert [[m.content for m in event.data] for event in log.events] == [["1", "2"]]


@pytest.mark.asyncio
async def test_a_caller_leaving_early_cancels_each_step_once() -> None:
    started = asyncio.Event()
    counts: list[int] = []

    async def waits(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        emit_delta("first")
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            task = asyncio.current_task()
            assert task is not None
            counts.append(task.cancelling())
            raise
        yield reply("never")

    definition = workflow(
        node("waits", waits, InputTopic(name="input"), OutputTopic(name="out"))
    )
    outputs = definition.invoke(input_event(), stream=True)
    async with asyncio.timeout(5):
        await anext(outputs)
        await started.wait()
        await outputs.aclose()
    assert counts == [1]


@pytest.mark.asyncio
async def test_an_abort_during_a_commit_still_cancels_a_closing_step(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    # Regression: wherever the caller's abort lands in the coordinator (here
    # in a commit's write), every step is cancelled again, including a failed
    # one still closing.
    committing = asyncio.Event()

    async def hold_commit(batch: list[Event]) -> None:
        if "c" in publishers(batch):
            committing.set()
            await asyncio.Event().wait()  # Held until the abort cancels it.

    Writes(monkeypatch, event_store, hold_commit)
    cleanup: list[str] = []

    class Rejecting(Topic):
        def prepare_publication(
            self, publish_event: PublishToTopicEvent
        ) -> PublishToTopicEvent:
            raise ValueError("invalid publication")

    class SlowClose(Node):
        """A node whose stream takes long to clean up as it is closed."""

        async def invoke(
            self, invoke_context: InvokeContext, node_input: list[Any]
        ) -> AsyncIterator[PublishToTopicEvent]:
            await committing.wait()
            try:
                async for publication in super().invoke(invoke_context, node_input):
                    yield publication
            finally:
                try:
                    await asyncio.sleep(3)
                    cleanup.append("closed")
                except asyncio.CancelledError:
                    cleanup.append("cancelled")
                    raise

    source = InputTopic(name="input")
    bad = SlowClose(
        name="bad",
        tool=ScriptedTool(script=emits("x")),
        subscribed_expressions=[TopicExpr(topic=source)],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=Rejecting(name="mid"))]
        ),
    )

    async def early(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        emit_delta("first")
        emit_delta("second")
        yield reply("done")

    definition = workflow(
        node("early", early, source, OutputTopic(name="out")),
        node("c", emits("side"), source, Topic(name="side")),
        bad,
    )
    outputs = definition.invoke(input_event(), stream=True)
    async with asyncio.timeout(5):
        await anext(outputs)
        await until(
            lambda: any(run._failure for run in definition._active_runs.values())
        )
        started = asyncio.get_running_loop().time()
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.2):
                # "second" is queued: the read sees the failure and closes, and
                # the timeout aborts that close.
                await anext(outputs)
        assert asyncio.get_running_loop().time() - started < 2
    assert cleanup == ["cancelled"]


@pytest.mark.asyncio
async def test_a_coordinator_cancelled_before_it_ran_ends_the_stream(
    event_store: EventStore,
) -> None:
    definition = workflow(
        node("emit", emits("a"), InputTopic(name="input"), OutputTopic(name="out"))
    )
    outputs = WorkflowRun(definition, event_store).run(input_event())
    reader = asyncio.ensure_future(anext(outputs))
    await asyncio.sleep(0)  # The reader starts the run; its coordinator waits.
    [coordinator] = tasks_named(definition.name)
    coordinator.cancel("shutdown")
    async with asyncio.timeout(5):
        with pytest.raises(WorkflowError, match="unexpectedly cancelled"):
            await reader


@pytest.mark.asyncio
async def test_a_node_with_backlog_does_not_wait_for_an_unrelated_write(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    release = asyncio.Event()
    x_running = asyncio.Event()

    async def hold_x_commit(batch: list[Event]) -> None:
        if "x" in publishers(batch):
            await release.wait()

    writes = Writes(monkeypatch, event_store, hold_x_commit)

    async def second(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await x_running.wait()
        yield reply("m2")

    async def x(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        if call == 1:
            x_running.set()
            await until(lambda: writes.published("mid", publisher="p2"))
        yield reply("|".join(inputs))

    source, mid = InputTopic(name="input"), Topic(name="mid")
    definition = workflow(
        node("p1", emits("m1"), source, mid),
        node("p2", second, source, mid),
        node("x", x, mid, OutputTopic(name="out")),
    )
    drained = asyncio.ensure_future(drain(definition, input_event()))
    async with asyncio.timeout(5):
        # x's first commit is held; its backlog (m2) runs anyway.
        await until(lambda: len(calls(definition, "x")) == 2)
        release.set()
        assert sorted(await drained) == ["m1", "m2"]


@pytest.mark.asyncio
async def test_a_publishing_failure_is_recorded_as_the_nodes_failure(
    event_store: EventStore,
) -> None:
    from grafi.common.events.component_events import NodeFailedEvent

    class Rejecting(Topic):
        def prepare_publication(
            self, publish_event: PublishToTopicEvent
        ) -> PublishToTopicEvent:
            raise ValueError("invalid publication")

    definition = workflow(
        node("n", emits("x"), InputTopic(name="input"), Rejecting(name="mid")),
        node("sink", echo, Rejecting(name="mid"), OutputTopic(name="out")),
    )
    with pytest.raises(NodeExecutionError, match="invalid publication") as raised:
        await drain(definition, input_event())
    assert not getattr(raised.value, "__notes__", [])  # Recorded once.
    failed = [
        e for e in await event_store.get_events() if isinstance(e, NodeFailedEvent)
    ]
    assert [event.name for event in failed] == ["n"]


@pytest.mark.asyncio
async def test_a_run_stopped_before_it_started_does_nothing(
    event_store: EventStore,
) -> None:
    definition = workflow(
        node("emit", emits("a"), InputTopic(name="input"), OutputTopic(name="out"))
    )
    run = WorkflowRun(definition, event_store)
    run.stop()
    event = input_event()
    async with asyncio.timeout(5):
        assert [o async for o in run.run(event)] == []
    assert calls(definition, "emit") == []
    assert (
        await event_store.get_agent_events(event.invoke_context.assistant_request_id)
        == []
    )


@pytest.mark.asyncio
async def test_a_run_stopped_while_its_history_loads_does_nothing(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    # Regression: a stop that arrived while the history loaded still stored
    # the input, which a later resume of the request then replayed.
    loading = asyncio.Event()
    get_agent_events = event_store.get_agent_events

    async def slow_get_agent_events(
        assistant_request_id: str, **kwargs: Any
    ) -> list[Event]:
        loading.set()
        await asyncio.sleep(0.01)
        return await get_agent_events(assistant_request_id, **kwargs)

    monkeypatch.setattr(event_store, "get_agent_events", slow_get_agent_events)
    definition = workflow(
        node("emit", emits("a"), InputTopic(name="input"), OutputTopic(name="out"))
    )
    run = WorkflowRun(definition, event_store)
    event = input_event()

    async def consume() -> list[Any]:
        return [o async for o in run.run(event)]

    consumer = asyncio.create_task(consume())
    await loading.wait()
    run.stop()
    async with asyncio.timeout(5):
        assert await consumer == []
    assert calls(definition, "emit") == []
    assert await get_agent_events(event.invoke_context.assistant_request_id) == []


@pytest.mark.asyncio
async def test_a_coordinator_cancelled_with_its_caller_is_noted(
    event_store: EventStore,
) -> None:
    # Regression: the caller's close can see the coordinator done before the
    # coordinator's done callback has run; the run's failure is noted anyway.
    definition = workflow(
        node("emit", emits("a"), InputTopic(name="input"), OutputTopic(name="out"))
    )
    outputs = WorkflowRun(definition, event_store).run(input_event())
    reader = asyncio.ensure_future(anext(outputs))
    await asyncio.sleep(0)  # The reader starts the run; its coordinator waits.
    [coordinator] = tasks_named(definition.name)
    reader.cancel()
    coordinator.cancel("shutdown")
    async with asyncio.timeout(5):
        await asyncio.wait({reader})
    assert reader.cancelled()
    with pytest.raises(asyncio.CancelledError) as raised:
        reader.result()
    notes = getattr(raised.value, "__notes__", [])
    assert any("unexpectedly cancelled" in note for note in notes)


@pytest.mark.asyncio
async def test_a_coordinator_cancelled_while_steps_stop_records_it() -> None:
    # Regression: an outside cancellation is the run's failure wherever it
    # lands, including while the run waits for its stopped steps.
    stopping = asyncio.Event()

    async def slow(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopping.set()
            await asyncio.Event().wait()  # Stops when cancelled again.
        yield reply("never")

    source = InputTopic(name="input")
    definition = workflow(
        node("quick", emits("a"), source, OutputTopic(name="out")),
        node("slow", slow, source, Topic(name="side")),
    )
    outputs = definition.invoke(input_event())
    async with asyncio.timeout(5):
        await anext(outputs)
        definition.stop()
        await stopping.wait()
        [coordinator] = tasks_named(definition.name)
        coordinator.cancel("shutdown")
        await asyncio.wait({coordinator})
        with pytest.raises(WorkflowError, match="unexpectedly cancelled"):
            await anext(outputs)


@pytest.mark.asyncio
async def test_a_sequential_fan_in_runs_once_on_all_its_inputs() -> None:
    # Regression: a sequential run takes one step after the other, so the
    # node both branches feed runs once, on both outputs, as on main.
    source, a, b, c = (
        InputTopic(name="input"),
        Topic(name="a"),
        Topic(name="b"),
        Topic(name="c"),
    )
    definition = workflow(
        node("A", emits("A1"), source, a, b),
        node("B", emits("B1"), a, c),
        node("C", emits("C1"), b, c),
        node("D", echo, c, OutputTopic(name="out")),
    )
    assert await drain(definition, input_event(), sequential=True) == ["B1|C1"]
    assert calls(definition, "D") == [["B1", "C1"]]


@pytest.mark.asyncio
async def test_repeated_outside_cancellations_are_one_failure() -> None:
    stopping = asyncio.Event()

    async def slow(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopping.set()
            for _ in range(3):  # Ignores the next cancellations, then stops.
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    pass
        yield reply("never")

    source = InputTopic(name="input")
    definition = workflow(
        node("quick", emits("a"), source, OutputTopic(name="out")),
        node("slow", slow, source, Topic(name="side")),
    )
    outputs = definition.invoke(input_event())
    async with asyncio.timeout(5):
        await anext(outputs)
        definition.stop()
        await stopping.wait()
        [coordinator] = tasks_named(definition.name)
        while not coordinator.done():
            coordinator.cancel("shutdown")
            await asyncio.sleep(0)
        with pytest.raises(WorkflowError, match="unexpectedly cancelled") as raised:
            await anext(outputs)
    notes = getattr(raised.value, "__notes__", [])
    assert not any("unexpectedly cancelled" in note for note in notes)


@pytest.mark.asyncio
async def test_a_step_asking_to_stop_from_a_child_task_finishes(
    event_store: EventStore,
) -> None:
    # Regression: the step is spared whichever of its tasks calls stop(), for
    # example one asyncio.gather() runs.
    definitions: list[EventDrivenWorkflow] = []

    async def stop_the_workflow() -> None:
        definitions[0].stop()

    async def finish(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await asyncio.gather(stop_the_workflow())
        await asyncio.sleep(0)
        yield reply("final answer")

    definition = workflow(
        node("finish", finish, InputTopic(name="input"), OutputTopic(name="out"))
    )
    definitions.append(definition)
    event = input_event()
    assert await drain(definition, event) == ["final answer"]
    assert await drain(definition, event) == []  # Not run again.
    assert len(calls(definition, "finish")) == 1


@pytest.mark.asyncio
async def test_a_step_stopping_the_run_from_a_nested_workflow_finishes() -> None:
    # Regression: a nested workflow's step must not hide the outer step that
    # runs it; that outer step stopped the outer run, so it is left to finish.
    outer: list[EventDrivenWorkflow] = []

    async def stop_outer(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        outer[0].stop()
        await asyncio.sleep(0)
        yield reply("inner")

    inner = workflow(
        node("stops", stop_outer, InputTopic(name="input"), OutputTopic(name="out"))
    )

    async def host(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        # A request of its own, as a nested workflow needs.
        answers = [o.data[0].content async for o in inner.invoke(input_event())]
        yield reply("host:" + "|".join(str(answer) for answer in answers))

    outer.append(
        workflow(node("host", host, InputTopic(name="input"), OutputTopic(name="out")))
    )
    assert await drain(outer[0], input_event()) == ["host:inner"]


@pytest.mark.asyncio
async def test_a_later_stop_cancels_a_failed_step_still_closing() -> None:
    # Regression: a stop asked for from outside, after a failure left the
    # failed step to close, cancels that step too.
    closing = asyncio.Event()
    cleanup: list[str] = []

    class Rejecting(Topic):
        def prepare_publication(
            self, publish_event: PublishToTopicEvent
        ) -> PublishToTopicEvent:
            raise ValueError("invalid publication")

    class HangingClose(Node):
        """A node whose stream's cleanup never ends unless cancelled."""

        async def invoke(
            self, invoke_context: InvokeContext, node_input: list[Any]
        ) -> AsyncIterator[PublishToTopicEvent]:
            try:
                async for publication in super().invoke(invoke_context, node_input):
                    yield publication
            finally:
                closing.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cleanup.append("cancelled")
                    raise

    definition = workflow(
        HangingClose(
            name="bad",
            tool=ScriptedTool(script=emits("x")),
            subscribed_expressions=[TopicExpr(topic=InputTopic(name="input"))],
            publisher_router=PublisherRouter(
                routes=[PublishRoute(topic=Rejecting(name="mid"))]
            ),
        ),
        node("sink", echo, Rejecting(name="mid"), OutputTopic(name="out")),
    )
    outputs = definition.invoke(input_event())
    reader = asyncio.ensure_future(anext(outputs))
    async with asyncio.timeout(5):
        await closing.wait()
        definition.stop()  # From outside the run's steps.
        with pytest.raises(NodeExecutionError, match="invalid publication"):
            await reader
    assert cleanup == ["cancelled"]


# --------------------------------------------------------------------------- #
# Recovery
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "history, error",
    [
        ("gap", "missing or conflicting offsets: expected offset 1, found 2"),
        ("conflict", "missing or conflicting offsets: expected offset 1, found 0"),
        ("unpublished", "no publication at consumed offset 1"),
        ("unknown topic", "unknown topic 'gone'"),
    ],
)
async def test_recovery_rejects_incomplete_history(
    event_store: EventStore, history: str, error: str
) -> None:
    definition = workflow(
        node("echo", echo, InputTopic(name="input"), OutputTopic(name="out"))
    )
    event = input_event()

    def published(topic: str, offset: int) -> PublishToTopicEvent:
        return event.model_copy(
            update={"event_id": uuid.uuid4().hex, "name": topic, "offset": offset}
        )

    consumed = ConsumeFromTopicEvent(
        name="input",
        offset=1,
        consumer_name="echo",
        consumer_type="Node",
        invoke_context=event.invoke_context,
        data=event.data,
    )
    records: list[TopicEvent] = {
        "gap": [published("input", 0), published("input", 2)],
        "conflict": [published("input", 0), published("input", 0)],
        "unpublished": [published("input", 0), consumed],
        "unknown topic": [published("gone", 0)],
    }[history]
    await event_store.record_events(records)
    with pytest.raises(WorkflowError, match=re.escape(error)):
        await drain(definition, event)
    assert calls(definition, "echo") == []
    stored = await event_store.get_agent_events(
        event.invoke_context.assistant_request_id
    )
    assert len([e for e in stored if isinstance(e, TopicEvent)]) == len(records)


@pytest.mark.asyncio
async def test_outputs_not_handed_over_are_delivered_again_on_resume() -> None:
    source = InputTopic(name="input")
    first, second = OutputTopic(name="first"), OutputTopic(name="second")
    # One step, two outputs: both committed before the caller takes the first.
    definition = workflow(node("reply", emits("one"), source, first, second))
    event = input_event()
    outputs = definition.invoke(event)
    async with asyncio.timeout(5):
        assert (await anext(outputs)).name == "first"
        await outputs.aclose()  # Acknowledges what was handed over: the first.
    async with asyncio.timeout(5):
        assert [o.name async for o in definition.invoke(event)] == ["second"]
    assert await drain(definition, event) == []
    assert calls(definition, "reply") == [["hello"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_human_answer_is_routed_to_its_paired_topic_once(
    sequential: bool,
) -> None:
    response = InWorkflowInputTopic(name="human_response")
    request = InWorkflowOutputTopic(
        name="human_request", paired_in_workflow_input_topic_names=["human_response"]
    )
    definition = workflow(
        node("asker", emits("your name?"), InputTopic(name="input"), request),
        node("answerer", echo, response, OutputTopic(name="out")),
    )
    first = input_event("register me")
    async with asyncio.timeout(5):
        outputs = definition.invoke(first, sequential)
        prompt = await anext(outputs)
        await outputs.aclose()
    assert prompt.data[0].content == "your name?"
    answer = input_event("Alice").model_copy(
        update={
            "invoke_context": first.invoke_context,
            "consumed_event_ids": [prompt.event_id],
        }
    )
    assert await drain(definition, answer, sequential) == ["Alice"]
    # The same answer again (a client's retry) publishes nothing new.
    assert await drain(definition, answer, sequential) == []
    assert calls(definition, "answerer") == [["Alice"]]
    assert calls(definition, "asker") == [["register me"]]


@pytest.mark.asyncio
async def test_an_answer_to_a_request_never_acknowledged_is_logged(
    monkeypatch: pytest.MonkeyPatch, event_store: EventStore
) -> None:
    # Regression: an answer citing a request whose acknowledgement was never
    # stored matched nothing and was dropped without a trace.
    response = InWorkflowInputTopic(name="human_response")
    request = InWorkflowOutputTopic(
        name="human_request", paired_in_workflow_input_topic_names=["human_response"]
    )
    definition = workflow(
        node("asker", emits("your name?"), InputTopic(name="input"), request),
        node("answerer", echo, response, OutputTopic(name="out")),
    )
    record_events = event_store.record_events

    async def losing_acknowledgements(events: Sequence[Event]) -> None:
        if any(
            isinstance(event, ConsumeFromTopicEvent)
            and event.consumer_name == definition.name
            for event in events
        ):
            raise RuntimeError("acknowledgement lost")
        await record_events(events)

    first = input_event("register me")
    async with asyncio.timeout(5):
        outputs = definition.invoke(first)
        prompt = await anext(outputs)
        monkeypatch.setattr(event_store, "record_events", losing_acknowledgements)
        with pytest.raises(WorkflowError) as raised:
            await outputs.aclose()
    assert "acknowledgement lost" in str(raised.value.__cause__)
    monkeypatch.setattr(event_store, "record_events", record_events)
    answer = input_event("Alice").model_copy(
        update={
            "invoke_context": first.invoke_context,
            "consumed_event_ids": [prompt.event_id],
        }
    )
    messages: list[str] = []
    handler = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        async with asyncio.timeout(5):
            outputs = definition.invoke(answer)
            again = await anext(outputs)
            await outputs.aclose()
    finally:
        logger.remove(handler)
    assert again.data[0].content == "your name?"  # Delivered again, to answer.
    assert calls(definition, "answerer") == []
    [warning] = [message for message in messages if prompt.event_id in message]
    assert "it answers nothing" in warning
    # Answering the request delivered again, citing the lost one too, works.
    messages.clear()
    retry = answer.model_copy(
        update={
            "event_id": uuid.uuid4().hex,
            "consumed_event_ids": [again.event_id, prompt.event_id],
        }
    )
    handler = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        assert await drain(definition, retry) == ["Alice"]
    finally:
        logger.remove(handler)
    [warning] = [message for message in messages if prompt.event_id in message]
    assert "it answers nothing" not in warning


@pytest.mark.asyncio
async def test_a_workflows_span_is_current_only_while_it_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Regression: the workflow's span stayed current in the caller's context
    # between reads, and for good once an abandoned stream was closed from
    # another task (which could not detach it), parenting the caller's later
    # spans under it.
    import gc

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from grafi.runtime.execution_services import ExecutionServices
    from grafi.runtime.execution_services import bind_services

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    services = ExecutionServices(
        event_store=EventStoreInMemory(), tracer=provider.get_tracer("test")
    )
    definition = workflow(
        node("emit", emits("a"), InputTopic(name="input"), OutputTopic(name="out"))
    )

    def current_span_is_set() -> bool:
        return trace.get_current_span().get_span_context().is_valid

    with bind_services(services):
        async with asyncio.timeout(5):
            outputs = definition.invoke(input_event())
            await anext(outputs)
            assert not current_span_is_set()
            await outputs.aclose()
        spans = {span.name: span for span in exporter.get_finished_spans()}
        workflow_span = spans[f"{definition.name}.invoke"]
        node_span = spans["emit.invoke"]
        assert node_span.parent is not None
        assert node_span.parent.span_id == workflow_span.context.span_id

        abandoned = definition.invoke(input_event())
        await anext(abandoned)
        del abandoned
        gc.collect()
        async with asyncio.timeout(5):
            while not any(  # The loop closes the abandoned stream.
                span.name == f"{definition.name}.invoke"
                for span in exporter.get_finished_spans()[len(spans) :]
            ):
                await asyncio.sleep(0.001)
        assert not current_span_is_set()
    assert "Failed to detach context" not in caplog.text


@pytest.mark.asyncio
async def test_a_failed_components_span_records_its_exception_once() -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    from opentelemetry.trace import StatusCode

    from grafi.runtime.execution_services import ExecutionServices
    from grafi.runtime.execution_services import bind_services

    async def fail(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        raise ValueError("tool broke")
        yield reply("never")

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    services = ExecutionServices(
        event_store=EventStoreInMemory(), tracer=provider.get_tracer("test")
    )
    definition = workflow(
        node("boom", fail, InputTopic(name="input"), OutputTopic(name="out"))
    )
    with bind_services(services):
        with pytest.raises(NodeExecutionError):
            await drain(definition, input_event())
    spans = {span.name: span for span in exporter.get_finished_spans()}
    for name in ("boom.invoke", f"{definition.name}.invoke"):
        span = spans[name]
        assert span.status.status_code is StatusCode.ERROR
        assert [event.name for event in span.events].count("exception") == 1


def test_an_exit_from_a_tool_lets_the_loop_runner_clean_up() -> None:
    # Regression: a tool's SystemExit leaves the loop at once; asyncio.run()
    # then cancels every task to clean up, and each caller of the run raised
    # the exit again, cutting that cleanup short: another request's run was
    # left pending on the closed loop.
    async def script(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        await asyncio.sleep(0.02)
        if inputs == ["exit"]:
            raise SystemExit("tool called sys.exit()")
        await asyncio.sleep(1)
        yield reply("done")

    definition = workflow(
        node("n", script, InputTopic(name="input"), OutputTopic(name="out"))
    )
    loops: list[asyncio.AbstractEventLoop] = []

    async def read(content: str) -> None:
        async for _ in definition.invoke(input_event(content)):
            pass

    async def main() -> None:
        loops.append(asyncio.get_running_loop())
        async with asyncio.TaskGroup() as group:
            group.create_task(read("exit"))
            group.create_task(read("stay"))

    with pytest.raises(SystemExit, match="tool called sys.exit"):
        asyncio.run(main())
    assert [task for task in asyncio.all_tasks(loops[0]) if not task.done()] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_a_node_that_publishes_nothing_is_not_a_failure(
    event_store: EventStore, sequential: bool
) -> None:
    # Regression (also on main): a node whose tool yielded nothing failed the
    # run with an IndexError while recording its respond event.
    from grafi.common.events.component_events import NodeRespondEvent

    async def quiet(call: int, inputs: list[str]) -> AsyncIterator[Messages]:
        return
        yield reply("never")

    source = InputTopic(name="input")
    definition = workflow(
        node("quiet", quiet, source, Topic(name="side")),
        node("emit", emits("a"), source, OutputTopic(name="out")),
    )
    event = input_event()
    assert await drain(definition, event, sequential) == ["a"]
    history = await event_store.get_agent_events(
        event.invoke_context.assistant_request_id
    )
    [responded] = [
        e for e in history if isinstance(e, NodeRespondEvent) and e.name == "quiet"
    ]
    assert responded.output_data is None
    stored = json.loads(json.dumps(default_event_codec.encode(responded)))
    assert stored["output_data"] is None
    assert default_event_codec.decode(stored) == responded
