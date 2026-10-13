"""Regression tests for parallel input readiness and owned read tasks."""

import asyncio
import threading
from typing import Any

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field
from pydantic import PrivateAttr

from grafi.assistants.assistant import Assistant
from grafi.common.event_stores.event_store import EventStore
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
from grafi.runtime import GrafiRuntime
from grafi.tools.tool import Tool
from grafi.topics.expressions.topic_expression import CombinedExpr
from grafi.topics.expressions.topic_expression import LogicalOp
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl import async_output_queue
from grafi.workflows.impl.async_node_tracker import AsyncNodeTracker
from grafi.workflows.impl.async_output_queue import AsyncOutputQueue
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.impl.parallel_engine import _invoke_node
from grafi.workflows.impl.parallel_engine import invoke_parallel
from grafi.workflows.impl.workflow_run import WorkflowRun


class RecordingTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    calls: list[list[str]] = Field(default_factory=list)
    _called: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.calls.append([message.content for message in input_data])
        self._called.set()
        yield [Message(role="assistant", content="joined")]

    @classmethod
    async def from_dict(cls, data: dict[str, Any]) -> "RecordingTool":
        return cls()


def make_run(op: LogicalOp = LogicalOp.AND) -> tuple[WorkflowRun, Node]:
    a, b = InputTopic(name="a"), Topic(name="b")
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


def event(content: str) -> PublishToTopicEvent:
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
@pytest.mark.parametrize("swallow_cancellation", [False, True])
async def test_repeated_a_does_not_satisfy_and_join(
    monkeypatch: pytest.MonkeyPatch, delayed_b: bool, swallow_cancellation: bool
) -> None:
    run, node = make_run()
    read_rounds = asyncio.Queue()
    readers = []
    queue = run.topics["b"].event_queue
    original_fetch = queue.fetch

    async def fetch(*args: Any, **kwargs: Any) -> list[TopicEvent]:
        readers.append(asyncio.current_task())
        read_rounds.put_nowait(None)
        try:
            return await original_fetch(*args, **kwargs)
        except asyncio.CancelledError:
            if swallow_cancellation:
                # Compatibility with queues that turn cancellation into an
                # empty batch. They still terminate; readiness must stay false.
                return []
            raise

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
            assert await run.tracker.get_activity_count() == int(delayed_b)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
    assert readers and all(reader.done() for reader in readers)


@pytest.mark.asyncio
async def test_empty_read_does_not_make_a_topic_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, node = make_run()
    second_read = asyncio.Event()
    calls = 0

    async def fetch(*args: Any, **kwargs: Any) -> list[TopicEvent]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        second_read.set()
        return await asyncio.Future()

    monkeypatch.setattr(run.topics["b"].event_queue, "fetch", fetch)
    await run.tracker.on_messages_published(1)
    await run.topics["a"].publish_data(event("A1"))
    worker = asyncio.create_task(_invoke_node(run, event("A1").invoke_context, node))
    try:
        await asyncio.wait_for(second_read.wait(), 2)
        assert node.tool.calls == []
        assert await run.tracker.get_activity_count() == 0
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_or_join_accepts_one_nonempty_topic() -> None:
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
async def test_read_failure_reaches_caller_without_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, node = make_run()
    failure = RuntimeError("transport failed")
    readers = []

    async def fetch(*args: Any, **kwargs: Any) -> list[TopicEvent]:
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
async def test_cancellation_joins_readers_before_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, node = make_run()
    started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    readers = []

    async def fetch(*args: Any, **kwargs: Any) -> list[TopicEvent]:
        readers.append(asyncio.current_task())
        started.set()
        try:
            return await asyncio.Future()
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
async def test_public_workflow_stop_from_another_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, node = make_run(LogicalOp.OR)
    workflow = EventDrivenWorkflow.builder().node(node).build()
    started, closed = asyncio.Event(), asyncio.Event()
    stop_threads: list[int] = []
    force_stop_sync = AsyncNodeTracker.force_stop_sync

    def record_stop(self: AsyncNodeTracker) -> None:
        stop_threads.append(threading.get_ident())
        force_stop_sync(self)

    monkeypatch.setattr(AsyncNodeTracker, "force_stop_sync", record_stop)

    async def invoke(
        self: RecordingTool, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        try:
            started.set()
            await asyncio.Future()
            yield []
        finally:
            closed.set()

    monkeypatch.setattr(RecordingTool, "invoke", invoke)

    async def drain() -> list[ConsumeFromTopicEvent]:
        return [
            output
            async for output in GrafiRuntime().invoke(
                Assistant(workflow=workflow), event("input")
            )
        ]

    task = asyncio.create_task(drain())
    try:
        async with asyncio.timeout(2):
            await started.wait()
            await asyncio.to_thread(workflow.stop)
            assert await task == []
        assert closed.is_set()
        assert not workflow._active_runs
        assert set(stop_threads) == {threading.get_ident()}
    finally:
        workflow.stop()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("is_sequential", [False, True])
async def test_empty_subscriptions_rejected_before_input_is_saved(
    event_store: EventStore, is_sequential: bool
) -> None:
    _, node = make_run(LogicalOp.OR)
    empty = Node(name="empty", type="Node", tool=RecordingTool())
    with pytest.raises(WorkflowError, match="at least one subscription"):
        EventDrivenWorkflow.builder().node(node).node(empty).build()
    input_event = event("input")
    assert (
        await event_store.get_agent_events(
            input_event.invoke_context.assistant_request_id
        )
        == []
    )
    workflow = EventDrivenWorkflow.builder().node(node).build()
    async with asyncio.timeout(2):
        outputs = [
            message.content
            async for output in workflow.invoke(input_event, is_sequential)
            for message in output.data
        ]
    assert outputs == ["joined"]


@pytest.mark.asyncio
async def test_unexpected_reader_cancellation_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, node = make_run()
    calls = 0

    async def fetch(*args: Any, **kwargs: Any) -> list[TopicEvent]:
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError("transport interrupted")

    monkeypatch.setattr(run.topics["a"].event_queue, "fetch", fetch)
    await run.tracker.on_messages_published(1)
    async with asyncio.timeout(2):
        with pytest.raises(NodeExecutionError) as raised:
            async for _ in invoke_parallel(run, event("input")):
                pytest.fail("An interrupted read must not invoke the node")
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert "unexpectedly cancelled" in str(raised.value.__cause__)
    assert isinstance(raised.value.__cause__.__cause__, asyncio.CancelledError)
    assert str(raised.value.__cause__.__cause__) == "transport interrupted"
    assert raised.value.__cause__.__cause__.__traceback__ is not None
    assert calls == 1
    assert node.tool.calls == []


@pytest.mark.asyncio
async def test_node_failure_signals_stop_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, node = make_run(LogicalOp.OR)
    failure = NodeExecutionError(node_name=node.name, message="original failure")
    stop_calls = 0
    original_stop = run.tracker.force_stop_sync

    def stop() -> None:
        nonlocal stop_calls
        stop_calls += 1
        original_stop()

    async def invoke(
        self: RecordingTool, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        raise failure
        yield []  # pragma: no cover - declares the generator interface

    monkeypatch.setattr(run.tracker, "force_stop_sync", stop)
    monkeypatch.setattr(RecordingTool, "invoke", invoke)
    await run.tracker.on_messages_published(1)
    await run.topics["a"].publish_data(event("input"))
    with pytest.raises(NodeExecutionError) as raised:
        await _invoke_node(run, event("input").invoke_context, node)
    assert raised.value is failure
    assert stop_calls == 1


@pytest.mark.asyncio
async def test_sibling_fetched_input_replays_after_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, node = make_run()
    workflow = EventDrivenWorkflow.builder().node(node).build()
    input_event = event("A1")
    await run.init(input_event, is_sequential=False)
    a_fetched = asyncio.Event()
    a_queue = run.topics["a"].event_queue
    original_fetch = a_queue.fetch

    async def fetch_a(*args: Any, **kwargs: Any) -> list[TopicEvent]:
        records = await original_fetch(*args, **kwargs)
        a_fetched.set()
        return records

    async def fail_b(*args: Any, **kwargs: Any) -> list[TopicEvent]:
        await a_fetched.wait()
        raise RuntimeError("B transport failed")

    monkeypatch.setattr(a_queue, "fetch", fetch_a)
    monkeypatch.setattr(run.topics["b"].event_queue, "fetch", fail_b)
    async with asyncio.timeout(2):
        with pytest.raises(NodeExecutionError):
            await _invoke_node(run, input_event.invoke_context, node)
    assert a_queue._consumed[node.name] == 1
    assert a_queue._committed[node.name] == -1
    assert node.tool.calls == []
    assert not any(
        isinstance(record, ConsumeFromTopicEvent)
        for record in await run.event_store.get_agent_events(
            input_event.invoke_context.assistant_request_id
        )
    )
    recovered = WorkflowRun(workflow, run.event_store)
    await recovered.init(input_event, is_sequential=False)
    assert [
        message.content
        for record in await recovered.topics["a"].consume(node.name, timeout=0)
        for message in record.data
    ] == ["A1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("expected_stop", [False, True])
async def test_output_listener_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch, expected_stop: bool
) -> None:
    run, _ = make_run()
    queue = AsyncOutputQueue([run.topics["output"]], run.name, run.tracker)
    started = asyncio.Event()

    async def fetch(*args: Any, **kwargs: Any) -> list[TopicEvent]:
        started.set()
        return await asyncio.Future()

    monkeypatch.setattr(run.topics["output"].event_queue, "fetch", fetch)
    await run.tracker.on_messages_published(1)
    await queue.start_listeners()
    listener = queue._listener_tasks[0]
    try:
        await asyncio.wait_for(started.wait(), 2)
        if expected_stop:
            await queue.stop_listeners()
            assert queue._listener_error is None
        else:
            listener.cancel()
            with pytest.raises(asyncio.CancelledError):
                await listener
            with pytest.raises(RuntimeError, match="unexpectedly cancelled"):
                await anext(queue)
            assert isinstance(queue._listener_error.__cause__, asyncio.CancelledError)
        assert listener.cancelled()
    finally:
        await queue.stop_listeners()


@pytest.mark.asyncio
async def test_slow_reader_cleanup_does_not_end_run_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, node = make_run(LogicalOp.OR)
    monkeypatch.setattr(async_output_queue, "QUIESCENCE_POLL_INTERVAL", 0.01)
    started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def fetch(*args: Any, **kwargs: Any) -> list[TopicEvent]:
        started.set()
        try:
            return await asyncio.Future()
        finally:
            cleaning.set()
            await release.wait()

    monkeypatch.setattr(run.topics["b"].event_queue, "fetch", fetch)
    await run.tracker.on_messages_published(1)

    async def drain() -> list[str]:
        return [
            message.content
            async for output in invoke_parallel(run, event("A1"))
            for message in output.data
        ]

    task = asyncio.create_task(drain())
    try:
        async with asyncio.timeout(5):
            await started.wait()
            await run.topics["a"].publish_data(event("A1"))
            await cleaning.wait()
            assert await run._progress_possible()
            assert await run.tracker.get_activity_count() == 0
            # Cross every idle poll that previously caused a successful early
            # exit while the winning reader's cursor had already advanced.
            # Include the initial activity poll and scheduling slack. Shorten
            # the same interval the output loop uses rather than waiting 1.7s.
            poll_window = (
                async_output_queue.IDLE_POLLS_BEFORE_STOP + 3
            ) * async_output_queue.QUIESCENCE_POLL_INTERVAL
            done, _ = await asyncio.wait({task}, timeout=poll_window)
            assert not done
            assert not run._stop_requested
            assert node.tool.calls == []
            release.set()
            assert await task == ["joined"]
        assert await run.tracker.is_idle()
        assert await run.tracker.get_activity_count() == 1
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_reader_base_exception_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TransportFailure(BaseException):
        pass

    failure = TransportFailure("transport failed")
    run, node = make_run()

    async def fetch(*args: Any, **kwargs: Any) -> list[TopicEvent]:
        raise failure

    monkeypatch.setattr(run.topics["a"].event_queue, "fetch", fetch)
    await run.tracker.on_messages_published(1)
    async with asyncio.timeout(2):
        with pytest.raises(NodeExecutionError) as raised:
            async for _ in invoke_parallel(run, event("input")):
                pytest.fail("Failed reads cannot produce outputs")
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert raised.value.__cause__.__cause__ is failure
    assert node.tool.calls == []
    assert await run.tracker.is_idle()


@pytest.mark.asyncio
async def test_output_transport_timeout_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, _ = make_run()
    failure = TimeoutError("transport deadline exceeded")

    async def fetch(*args: Any, **kwargs: Any) -> list[TopicEvent]:
        raise failure

    monkeypatch.setattr(run.topics["output"].event_queue, "fetch", fetch)
    await run.tracker.on_messages_published(1)
    queue = AsyncOutputQueue([run.topics["output"]], run.name, run.tracker)
    await queue.start_listeners()
    try:
        async with asyncio.timeout(2):
            with pytest.raises(TimeoutError) as raised:
                await anext(queue)
        assert raised.value is failure
    finally:
        await queue.stop_listeners()
