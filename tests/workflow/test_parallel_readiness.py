"""Regression tests for parallel input readiness and owned read tasks."""

import asyncio

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field
from pydantic import PrivateAttr

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.tools.tool import Tool
from grafi.topics.expressions.topic_expression import CombinedExpr
from grafi.topics.expressions.topic_expression import LogicalOp
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.impl.parallel_engine import _invoke_node
from grafi.workflows.impl.parallel_engine import invoke_parallel
from grafi.workflows.impl.workflow_run import WorkflowRun


class RecordingTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    calls: list[list[str]] = Field(default_factory=list)
    _called: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)

    async def invoke(self, invoke_context, input_data):
        self.calls.append([message.content for message in input_data])
        self._called.set()
        yield [Message(role="assistant", content="joined")]

    @classmethod
    async def from_dict(cls, data):
        return cls()


def make_run(op=LogicalOp.AND):
    a, b = InputTopic(name="a"), InputTopic(name="b")
    node = Node(
        name="join",
        type="Node",
        tool=RecordingTool(),
        subscribed_expressions=[
            CombinedExpr(op=op, left=TopicExpr(topic=a), right=TopicExpr(topic=b))
        ],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=OutputTopic(name="output"))]
        ),
    )
    workflow = EventDrivenWorkflow.builder().node(node).build()
    return WorkflowRun(workflow), node


def event(content):
    return PublishToTopicEvent(
        name="a",
        publisher_name="test",
        publisher_type="test",
        invoke_context=InvokeContext(
            conversation_id="c", invoke_id="i", assistant_request_id="r"
        ),
        data=[Message(role="user", content=content)],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("delayed_b", [False, True])
async def test_repeated_a_does_not_satisfy_and_join(monkeypatch, delayed_b):
    run, node = make_run()
    read_rounds = asyncio.Queue()
    readers = []
    queue = run.topics["b"].event_queue
    original_fetch = queue.fetch

    async def fetch(*args, **kwargs):
        readers.append(asyncio.current_task())
        read_rounds.put_nowait(None)
        return await original_fetch(*args, **kwargs)

    monkeypatch.setattr(queue, "fetch", fetch)
    await run.tracker.on_messages_published(3 if delayed_b else 2)
    worker = asyncio.create_task(_invoke_node(run, event("A1").invoke_context, node))
    try:
        async with asyncio.timeout(2):
            await read_rounds.get()
            await run.topics["a"].publish_data(event("A1"))
            await read_rounds.get()  # A1 buffered; cancelled B reader joined.
            await run.topics["a"].publish_data(event("A2"))
            await read_rounds.get()  # A2 buffered; still waiting for real B.
            assert node.tool.calls == []
            if delayed_b:
                await run.topics["b"].publish_data(event("B1"))
                await node.tool._called.wait()
                await read_rounds.get()  # Invocation completed; next input wait.
                assert node.tool.calls == [["A1", "A2", "B1"]]
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
    assert readers and all(reader.done() for reader in readers)


@pytest.mark.asyncio
async def test_empty_read_does_not_make_a_topic_ready(monkeypatch):
    run, node = make_run()
    second_read = asyncio.Event()
    calls = 0

    async def fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        second_read.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(run.topics["b"].event_queue, "fetch", fetch)
    await run.tracker.on_messages_published(1)
    await run.topics["a"].publish_data(event("A1"))
    worker = asyncio.create_task(_invoke_node(run, event("A1").invoke_context, node))
    try:
        await asyncio.wait_for(second_read.wait(), 2)
        assert node.tool.calls == []
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_or_join_accepts_one_nonempty_topic():
    run, node = make_run(LogicalOp.OR)
    await run.tracker.on_messages_published(1)
    await run.topics["a"].publish_data(event("A1"))
    worker = asyncio.create_task(_invoke_node(run, event("A1").invoke_context, node))
    try:
        await asyncio.wait_for(node.tool._called.wait(), 2)
        assert node.tool.calls == [["A1"]]
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_read_failure_reaches_caller_without_output(monkeypatch):
    run, node = make_run()
    failure = RuntimeError("transport failed")
    readers = []

    async def fetch(*args, **kwargs):
        readers.append(asyncio.current_task())
        raise failure

    monkeypatch.setattr(run.topics["a"].event_queue, "fetch", fetch)
    await run.tracker.on_messages_published(1)
    async with asyncio.timeout(2):
        with pytest.raises(NodeExecutionError) as raised:
            async for _ in invoke_parallel(run, event("input")):
                pytest.fail("No output should precede the read failure")
    assert raised.value.__cause__ is failure
    assert node.tool.calls == []
    assert all(reader.done() for reader in readers)


@pytest.mark.asyncio
async def test_cancellation_joins_readers_before_return(monkeypatch):
    run, node = make_run()
    started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    readers = []

    async def fetch(*args, **kwargs):
        readers.append(asyncio.current_task())
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    monkeypatch.setattr(run.topics["a"].event_queue, "fetch", fetch)
    worker = asyncio.create_task(_invoke_node(run, event("input").invoke_context, node))
    try:
        async with asyncio.timeout(2):
            await started.wait()
            worker.cancel()
            await cleaning.wait()
            assert not worker.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await worker
    finally:
        release.set()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
    assert all(reader.done() for reader in readers)
    assert node.tool.calls == []


@pytest.mark.asyncio
async def test_empty_subscriptions_rejected_before_workers_start(monkeypatch):
    run, node = make_run()
    empty = Node(name="empty", type="Node", tool=RecordingTool())
    run.nodes = {node.name: node, empty.name: empty}

    def unexpected_task(*args, **kwargs):
        pytest.fail("Validate all subscriptions before spawning workers")

    monkeypatch.setattr(asyncio, "create_task", unexpected_task)
    with pytest.raises(NodeExecutionError, match="at least one subscription"):
        async for _ in invoke_parallel(run, event("input")):
            pytest.fail("Invalid topology must not produce output")
