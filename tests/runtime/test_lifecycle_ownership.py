import asyncio
import sys
from typing import Any
from typing import AsyncIterator

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.async_lifecycle import owned_iterator
from grafi.common.exceptions import WorkflowError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.runtime import GrafiRuntime
from grafi.runtime.execution_services import current_services
from grafi.tools.tool import Tool
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from tests_integration.async_execution.support import input_event


class OpenStream(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    closed: asyncio.Event = Field(default_factory=asyncio.Event, exclude=True)
    scope_seen: Any = Field(default=None, exclude=True)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        services = current_services()
        try:
            yield [Message(role="assistant", content="first", is_streaming=True)]
            await asyncio.Event().wait()
        finally:
            self.scope_seen = current_services()
            assert self.scope_seen is services
            self.closed.set()


def stored_and_open_workflow(open_tool: Tool) -> EventDrivenWorkflow:
    """One node commits an output; another keeps its stream open until closed.

    Both write the output topic, so it is not streamed: the caller receives an
    output only once it is stored, and closing then acknowledges it.
    """
    from grafi.topics.expressions.topic_expression import TopicExpr
    from tests_integration.async_execution.support import EchoTool
    from tests_integration.async_execution.support import make_node

    source, out = InputTopic(name="input"), OutputTopic(name="out")
    done = make_node("done", EchoTool(), TopicExpr(topic=source), out)
    still_open = make_node("open", open_tool, TopicExpr(topic=source), out)
    return EventDrivenWorkflow.builder().node(done).node(still_open).build()


def fail_acknowledgements(
    monkeypatch: pytest.MonkeyPatch, runtime: GrafiRuntime, workflow_name: str
) -> asyncio.Event:
    """Make the workflow's acknowledgement write fail; returns when it began."""
    record = runtime.services.event_store.record_events
    began = asyncio.Event()

    async def record_events(events: Any) -> None:
        if any(getattr(e, "consumer_name", None) == workflow_name for e in events):
            began.set()
            raise OSError("final audit unavailable")
        await record(events)

    monkeypatch.setattr(runtime.services.event_store, "record_events", record_events)
    return began


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_cleanup", [False, True])
async def test_public_close_owns_children_before_return(
    monkeypatch: pytest.MonkeyPatch, fail_cleanup: bool
) -> None:
    tool = OpenStream()
    workflow = stored_and_open_workflow(tool)
    runtime = GrafiRuntime()
    if fail_cleanup:
        fail_acknowledgements(monkeypatch, runtime, workflow.name)
    output = runtime.invoke(Assistant(workflow=workflow), input_event())
    async with asyncio.timeout(3):
        assert (await anext(output)).data[0].content == "hello"
        if fail_cleanup:
            with pytest.raises(WorkflowError) as raised:
                await output.aclose()
            assert isinstance(raised.value.__cause__, OSError)
        else:
            await output.aclose()
    assert tool.closed.is_set()
    assert tool.scope_seen is runtime.services
    assert not workflow._active_runs


@pytest.mark.asyncio
async def test_close_failure_does_not_replace_primary_error() -> None:
    primary = ValueError("primary")

    async def source() -> AsyncIterator[int]:
        try:
            yield 1
        finally:
            raise OSError("secondary")

    with pytest.raises(ValueError) as raised:
        async with owned_iterator(source()) as child:
            assert await anext(child) == 1
            raise primary
    assert raised.value is primary
    assert any("OSError" in note for note in primary.__notes__)


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
@pytest.mark.parametrize("handled_exception", [False, True])
async def test_node_failure_surfaces_inside_caller_exception_handler(
    sequential: bool, handled_exception: bool
) -> None:
    from grafi.common.exceptions import NodeExecutionError
    from grafi.topics.expressions.topic_expression import TopicExpr
    from tests_integration.async_execution.support import EchoTool
    from tests_integration.async_execution.support import make_node

    class Fails(EchoTool):
        async def invoke(self, context: InvokeContext, messages: Messages) -> MsgsAGen:
            raise ValueError("node failed")
            yield []

    node = make_node(
        "fails",
        Fails(),
        TopicExpr(topic=InputTopic(name="input")),
        OutputTopic(name="out"),
    )
    assistant = Assistant(workflow=EventDrivenWorkflow.builder().node(node).build())
    runtime = GrafiRuntime()

    async def drain() -> None:
        with pytest.raises(NodeExecutionError):
            async for _ in runtime.invoke(assistant, input_event(), sequential):
                pass

    if handled_exception:
        try:
            raise LookupError("caller handled")
        except LookupError:
            await drain()
    else:
        await drain()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_node_cleanup", [False, True])
async def test_cancellation_during_close_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, fail_node_cleanup: bool
) -> None:
    class FailsAsItStops(OpenStream):
        async def invoke(
            self, invoke_context: InvokeContext, input_data: Messages
        ) -> MsgsAGen:
            try:
                async for messages in super().invoke(invoke_context, input_data):
                    yield messages
            except asyncio.CancelledError:
                raise RuntimeError("node cleanup failed") from None

    tool = FailsAsItStops() if fail_node_cleanup else OpenStream()
    workflow = stored_and_open_workflow(tool)
    runtime = GrafiRuntime()
    record = runtime.services.event_store.record_events
    entered = asyncio.Event()

    async def blocked_acknowledgement(events: Any) -> None:
        if any(getattr(e, "consumer_name", None) == workflow.name for e in events):
            entered.set()
            await asyncio.Event().wait()
        await record(events)

    monkeypatch.setattr(
        runtime.services.event_store, "record_events", blocked_acknowledgement
    )

    async def consumer() -> None:
        stream = runtime.invoke(Assistant(workflow=workflow), input_event())
        await anext(stream)
        await stream.aclose()

    closing = asyncio.create_task(consumer())
    async with asyncio.timeout(3):
        await entered.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
    assert tool.closed.is_set() and not workflow._active_runs


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
@pytest.mark.parametrize("timeout", [False, True])
async def test_aclosing_audit_failure_preserves_cancellation(
    monkeypatch: pytest.MonkeyPatch, sequential: bool, timeout: bool
) -> None:
    from contextlib import aclosing

    from grafi.common.events.topic_events.consume_from_topic_event import (
        ConsumeFromTopicEvent,
    )
    from grafi.topics.expressions.topic_expression import TopicExpr
    from tests_integration.async_execution.support import EchoTool
    from tests_integration.async_execution.support import make_node

    tool = EchoTool()
    node = make_node(
        "echo", tool, TopicExpr(topic=InputTopic(name="input")), OutputTopic(name="out")
    )
    workflow = EventDrivenWorkflow.builder().node(node).build()
    runtime = GrafiRuntime()
    record = runtime.services.event_store.record_events

    async def fail_final(events: Any) -> None:
        if any(
            isinstance(e, ConsumeFromTopicEvent) and e.consumer_name == workflow.name
            for e in events
        ):
            raise OSError("final audit write unavailable")
        await record(events)

    monkeypatch.setattr(runtime.services.event_store, "record_events", fail_final)
    ready = asyncio.Event()

    async def consumer() -> None:
        async with asyncio.timeout(10) as deadline:
            async with aclosing(
                runtime.invoke(Assistant(workflow=workflow), input_event(), sequential)
            ) as source:
                await anext(source)
                ready.set()
                if timeout:  # Expires while the caller waits, then closes.
                    deadline.reschedule(asyncio.get_running_loop().time() + 0.02)
                await asyncio.Event().wait()

    task = asyncio.create_task(consumer())
    async with asyncio.timeout(10):
        await ready.wait()
    if not timeout:
        task.cancel()
    with pytest.raises(TimeoutError if timeout else asyncio.CancelledError):
        await task
    assert task.cancelled() == (not timeout)
    assert not workflow._active_runs


@pytest.mark.asyncio
async def test_async_result_close_of_a_started_source_closes_it() -> None:
    from grafi.common.models.async_result import AsyncResult

    closed = asyncio.Event()

    async def source() -> Any:
        try:
            yield 1
            yield 2
        finally:
            closed.set()

    started = source()
    assert await anext(started) == 1  # Already running before it is wrapped.
    result = AsyncResult(started)
    await result.aclose()
    assert closed.is_set()
    with pytest.raises(StopAsyncIteration):
        await anext(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_acknowledgement_failure_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, sequential: bool
) -> None:
    from grafi.topics.expressions.topic_expression import TopicExpr
    from tests_integration.async_execution.support import EchoTool
    from tests_integration.async_execution.support import make_node

    node = make_node(
        "source",
        EchoTool(),
        TopicExpr(topic=InputTopic(name="input")),
        OutputTopic(name="out"),
    )
    workflow = EventDrivenWorkflow.builder().node(node).build()
    runtime = GrafiRuntime()
    fail_acknowledgements(monkeypatch, runtime, workflow.name)
    received = []
    async with asyncio.timeout(3):
        with pytest.raises(WorkflowError) as raised:
            async for output in runtime.invoke(
                Assistant(workflow=workflow), input_event(), sequential
            ):
                received.append(output)
    assert len(received) == 1  # Delivered once more when the request resumes.
    assert isinstance(raised.value.__cause__, OSError)


@pytest.mark.asyncio
async def test_node_failure_is_not_noted_as_its_own_cleanup_failure() -> None:
    from grafi.common.exceptions import NodeExecutionError
    from grafi.topics.expressions.topic_expression import TopicExpr
    from tests_integration.async_execution.support import EchoTool
    from tests_integration.async_execution.support import make_node

    go, failed = asyncio.Event(), asyncio.Event()

    class Fails(EchoTool):
        async def invoke(self, context: InvokeContext, messages: Messages) -> MsgsAGen:
            await go.wait()
            failed.set()
            raise ValueError("node failed")
            yield []

    class Chatty(EchoTool):
        async def invoke(self, context: InvokeContext, messages: Messages) -> MsgsAGen:
            for text in ("first", "second"):
                yield [Message(role="assistant", content=text, is_streaming=True)]

    source = InputTopic(name="input")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            make_node("fails", Fails(), TopicExpr(topic=source), OutputTopic(name="a"))
        )
        .node(
            make_node(
                "chatty", Chatty(), TopicExpr(topic=source), OutputTopic(name="b")
            )
        )
        .build()
    )
    with pytest.raises(NodeExecutionError) as raised:
        async with asyncio.timeout(5):
            async for _ in GrafiRuntime().invoke(
                Assistant(workflow=workflow), input_event()
            ):
                if not go.is_set():
                    # "second" is still queued; the output loop meets the failed
                    # node task when it hands that item over.
                    go.set()
                    await failed.wait()
                    await asyncio.sleep(0.01)
    notes = getattr(raised.value, "__notes__", [])
    assert not any("Secondary cleanup failure" in note for note in notes)


@pytest.mark.asyncio
async def test_sequential_close_acknowledges_only_delivered_outputs() -> None:
    from grafi.topics.expressions.topic_expression import TopicExpr
    from tests_integration.async_execution.support import EchoTool
    from tests_integration.async_execution.support import make_node

    class Three(EchoTool):
        async def invoke(self, context: InvokeContext, messages: Messages) -> MsgsAGen:
            for text in ("one", "two", "three"):
                yield [Message(role="assistant", content=text)]

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            make_node(
                "three",
                Three(),
                TopicExpr(topic=InputTopic(name="input")),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    runtime, event = GrafiRuntime(), input_event()
    output = runtime.invoke(Assistant(workflow=workflow), event, True)
    async with asyncio.timeout(3):
        assert (await anext(output)).data[0].content == "one"
        await output.aclose()
        resumed = [
            o.data[0].content
            async for o in runtime.invoke(Assistant(workflow=workflow), event, True)
        ]
    # Undelivered outputs come back; the received one may be delivered again.
    assert resumed[-2:] == ["two", "three"]


@pytest.mark.asyncio
async def test_async_result_await_after_a_failed_close_raises() -> None:
    from grafi.common.models.async_result import AsyncResult

    async def source() -> AsyncIterator[int]:
        try:
            yield 1
            yield 2
        finally:
            raise OSError("source close failed")

    started = source()
    assert await anext(started) == 1
    result = AsyncResult(started)
    with pytest.raises(OSError):
        await result.aclose()
    async with asyncio.timeout(1):
        with pytest.raises(RuntimeError, match="closed before its stream finished"):
            await result


@pytest.mark.asyncio
async def test_cancelling_follows_the_current_tasks_own_count() -> None:
    from grafi.common.async_lifecycle import cancelling

    async def being_cancelled() -> bool:
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            return cancelling()  # Still being cancelled while it unwinds.
        return False

    assert await asyncio.create_task(being_cancelled()) is True
    assert cancelling() is False  # Another task's count is not this one's.


@pytest.mark.asyncio
async def test_async_result_reads_after_end_do_not_hang() -> None:
    from grafi.common.models.async_result import AsyncResult

    async def source() -> AsyncIterator[int]:
        yield 1

    result = AsyncResult(source())
    async with asyncio.timeout(1):
        assert [item async for item in result] == [1]
        with pytest.raises(StopAsyncIteration):
            await anext(result)
        assert await result == []  # Data is consumed once.

    async def fails() -> AsyncIterator[int]:
        raise ValueError("source failed")
        yield 1

    failed = AsyncResult(fails())
    async with asyncio.timeout(1):
        with pytest.raises(ValueError):
            await anext(failed)
        with pytest.raises(ValueError):
            await anext(failed)  # Every read of a failed stream reports it.


@pytest.mark.asyncio
async def test_repeated_caller_cancellation_does_not_abandon_node_tasks() -> None:
    from contextlib import aclosing

    from grafi.topics.expressions.topic_expression import TopicExpr
    from tests_integration.async_execution.support import EchoTool
    from tests_integration.async_execution.support import make_node

    cleanup, release = asyncio.Event(), asyncio.Event()

    class Stubborn(EchoTool):
        async def invoke(self, context: InvokeContext, messages: Messages) -> MsgsAGen:
            try:
                yield [Message(role="assistant", content="first", is_streaming=True)]
                await asyncio.Event().wait()
            finally:
                cleanup.set()
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        continue

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            make_node(
                "stubborn",
                Stubborn(),
                TopicExpr(topic=InputTopic(name="input")),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    ready = asyncio.Event()

    async def consume() -> None:
        async with aclosing(
            GrafiRuntime().invoke(Assistant(workflow=workflow), input_event())
        ) as output:
            async for _ in output:
                ready.set()
                await asyncio.Event().wait()

    consumer = asyncio.create_task(consume())
    async with asyncio.timeout(5):
        await ready.wait()
        consumer.cancel()
        await cleanup.wait()
        await asyncio.sleep(0.05)  # The close waits for the stubborn step.
        consumer.cancel()  # A second cancellation while the close waits.
        await asyncio.sleep(0.01)
        assert not consumer.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await consumer
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "stubborn"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_async_result_reads_no_outputs_ahead_of_the_caller(
    sequential: bool,
) -> None:
    from grafi.common.models.async_result import async_func_wrapper
    from grafi.topics.expressions.topic_expression import TopicExpr
    from tests_integration.async_execution.support import EchoTool
    from tests_integration.async_execution.support import make_node

    class Three(EchoTool):
        async def invoke(self, context: InvokeContext, messages: Messages) -> MsgsAGen:
            for text in ("one", "two", "three"):
                yield [Message(role="assistant", content=text)]

    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            make_node(
                "three",
                Three(),
                TopicExpr(topic=InputTopic(name="input")),
                OutputTopic(name="out"),
            )
        )
        .build()
    )
    runtime, event = GrafiRuntime(), input_event()
    result = async_func_wrapper(
        runtime.invoke(Assistant(workflow=workflow), event, sequential)
    )
    async with asyncio.timeout(3):
        assert (await anext(result)).data[0].content == "one"
        await asyncio.sleep(0.05)  # Give a read-ahead producer every chance.
        await result.aclose()
        resumed = [
            o.data[0].content
            async for o in runtime.invoke(
                Assistant(workflow=workflow), event, sequential
            )
        ]
    # Outputs the caller never received come back when the request resumes.
    assert resumed == ["two", "three"]


@pytest.mark.asyncio
async def test_abandoned_async_result_closes_its_source() -> None:
    import gc

    from grafi.common.models.async_result import AsyncResult

    closed = asyncio.Event()

    async def source() -> AsyncIterator[int]:
        try:
            for item in range(3):
                yield item
        finally:
            closed.set()

    async def take_one() -> int:
        async for item in AsyncResult(source()):
            return item  # Leaves without aclose(), like an abandoned generator.
        raise AssertionError("no item")

    loop = asyncio.get_running_loop()
    reported: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _, context: reported.append(context))
    gc.disable()  # Rely on reference counting, as for an abandoned generator.
    try:
        assert await take_one() == 0
        async with asyncio.timeout(1):
            await closed.wait()
    finally:
        gc.enable()
        loop.set_exception_handler(None)
    assert not reported


@pytest.mark.asyncio
async def test_async_result_reports_its_failure_after_close() -> None:
    from grafi.common.models.async_result import AsyncResult

    async def fails() -> AsyncIterator[int]:
        yield 1
        raise ValueError("source failed")

    result = AsyncResult(fails())
    assert await anext(result) == 1
    with pytest.raises(ValueError):
        await anext(result)
    await result.aclose()
    with pytest.raises(ValueError):
        await anext(result)
    with pytest.raises(ValueError):
        await result


@pytest.mark.asyncio
async def test_async_result_repeated_reads_do_not_grow_the_traceback() -> None:
    import traceback

    from grafi.common.models.async_result import AsyncResult

    async def fails() -> AsyncIterator[int]:
        raise ValueError("source failed")
        yield 1

    result = AsyncResult(fails())
    lengths = []
    for _ in range(3):
        with pytest.raises(ValueError) as raised:
            await anext(result)
        lengths.append(len(traceback.extract_tb(raised.value.__traceback__)))
    assert lengths[0] == lengths[1] == lengths[2]


@pytest.mark.asyncio
async def test_async_result_cancelled_await_keeps_received_items_readable() -> None:
    from grafi.common.models.async_result import AsyncResult

    async def source() -> AsyncIterator[int]:
        yield 1
        await asyncio.Event().wait()
        yield 2

    result = AsyncResult(source())
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await result
    # The workflow counted item 1 as delivered when the result received it.
    assert await anext(result) == 1
    # The stream was cut short, so it never looks complete.
    with pytest.raises(RuntimeError, match="closed before its stream finished"):
        await anext(result)
    with pytest.raises(RuntimeError, match="closed before its stream finished"):
        await result


@pytest.mark.asyncio
async def test_failed_async_result_is_garbage_collected() -> None:
    import gc
    import weakref

    from grafi.common.models.async_result import AsyncResult

    async def fails() -> AsyncIterator[int]:
        raise ValueError("source failed")
        yield 1

    result = AsyncResult(fails())
    with pytest.raises(ValueError):
        await result
    collected = weakref.ref(result)
    del result
    gc.collect()
    assert collected() is None


@pytest.mark.asyncio
async def test_async_result_await_returns_only_items_not_yet_read() -> None:
    from grafi.common.models.async_result import AsyncResult

    async def source() -> AsyncIterator[int]:
        for item in range(3):
            yield item

    result = AsyncResult(source())
    async with asyncio.timeout(1):
        assert await anext(result) == 0
        # Item 0 was handed over (and acknowledged); it is not returned again.
        assert await result == [1, 2]


@pytest.mark.asyncio
async def test_failed_await_leaves_received_items_readable() -> None:
    from grafi.common.models.async_result import AsyncResult

    async def fails_after_two() -> AsyncIterator[int]:
        yield 1
        yield 2
        raise ValueError("source failed")

    result = AsyncResult(fails_after_two())
    async with asyncio.timeout(1):
        with pytest.raises(ValueError):
            await result
        # The workflow counted items 1 and 2 as delivered when they were read.
        received = []
        with pytest.raises(ValueError):
            async for item in result:
                received.append(item)
    assert received == [1, 2]


def test_cancelling_without_a_running_loop() -> None:
    from grafi.common.async_lifecycle import cancelling

    # For example a generator finalized after its event loop closed.
    assert cancelling() is False


@pytest.mark.asyncio
async def test_best_effort_exit_passes_the_body_failure_to_the_exit() -> None:
    from grafi.common.async_lifecycle import best_effort_exit

    seen: list[Any] = []

    class Client:
        async def __aenter__(self) -> str:
            return "client"

        async def __aexit__(self, *exc_info: Any) -> bool:
            seen.append(exc_info[0])
            return True  # It cannot suppress the failure.

    with pytest.raises(ValueError):
        async with best_effort_exit(Client(), "test client"):
            raise ValueError("call failed")
    assert seen == [ValueError]


@pytest.mark.asyncio
async def test_isolated_keeps_the_callers_cancellation_and_notes_the_failure() -> None:
    from grafi.common.async_lifecycle import isolated

    started = asyncio.Event()

    async def foreign_write() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise OSError("driver reports cancellation")

    raised: list[BaseException] = []

    async def caller() -> None:
        try:
            await isolated(foreign_write, "Writing")
        except asyncio.CancelledError as cancellation:
            raised.append(cancellation)
            raise

    task = asyncio.create_task(caller())
    await started.wait()
    task.cancel("shutdown")
    await asyncio.wait({task})
    assert task.cancelled()
    assert raised[0].args == ("shutdown",)  # The caller's own cancellation.
    assert any("driver reports cancellation" in n for n in raised[0].__notes__)


@pytest.mark.asyncio
async def test_isolated_foreign_code_cancelling_itself_is_a_failure() -> None:
    from grafi.common.async_lifecycle import isolated

    async def times_out() -> None:
        raise asyncio.CancelledError()  # A transport's own timeout.

    with pytest.raises(RuntimeError, match="Writing was unexpectedly cancelled") as e:
        await isolated(times_out, "Writing")
    assert isinstance(e.value.__cause__, asyncio.CancelledError)


class FailingCloseSource:
    """An empty source whose close fails."""

    def __aiter__(self) -> "FailingCloseSource":
        return self

    async def __anext__(self) -> int:
        raise StopAsyncIteration

    async def aclose(self) -> None:
        raise OSError("close failed")


@pytest.mark.asyncio
async def test_close_failure_for_a_cancelling_caller_frees_the_result() -> None:
    import gc
    import weakref

    from grafi.common.models.async_result import AsyncResult

    result = AsyncResult(FailingCloseSource())  # type: ignore[arg-type]
    collected = weakref.ref(result)

    async def close_while_cancelling(result: AsyncResult) -> None:
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            with pytest.raises(OSError):  # Raised in place of the cancellation.
                await result.aclose()
            raise

    closer = asyncio.create_task(close_while_cancelling(result))
    await asyncio.wait({closer})
    del result, closer
    gc.collect()
    assert collected() is None


@pytest.mark.asyncio
async def test_unstarted_source_close_failure_is_raised_by_aclose() -> None:
    from grafi.common.models.async_result import AsyncResult

    result = AsyncResult(FailingCloseSource())  # type: ignore[arg-type]
    with pytest.raises(OSError, match="close failed"):
        await result.aclose()
    with pytest.raises(StopAsyncIteration):  # A read of the closed result ends.
        await anext(result)


@pytest.mark.asyncio
async def test_async_result_close_failure_is_raised_despite_a_stale_cancel_count() -> (
    None
):
    from grafi.common.models.async_result import AsyncResult

    async def source() -> AsyncIterator[int]:
        try:
            yield 1
            yield 2
        finally:
            raise OSError("close failed")

    async def with_stale_count() -> None:
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass  # Swallowed without uncancel(): cancelling() stays at 1.
        result = AsyncResult(source())
        assert await anext(result) == 1
        with pytest.raises(OSError, match="close failed"):
            await result.aclose()

    await asyncio.create_task(with_stale_count())


@pytest.mark.asyncio
async def test_async_result_cancelled_read_closes_the_source() -> None:
    from grafi.common.models.async_result import AsyncResult

    closed = asyncio.Event()

    async def source() -> AsyncIterator[int]:
        try:
            yield 1
            await asyncio.Event().wait()
            yield 2
        finally:
            closed.set()

    result = AsyncResult(source())
    assert await anext(result) == 1
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await anext(result)  # As for a generator, this closes the source.
    assert closed.is_set()
    with pytest.raises(RuntimeError, match="closed before its stream finished"):
        await result


@pytest.mark.asyncio
async def test_async_result_await_raises_when_closed_mid_stream() -> None:
    from grafi.common.models.async_result import AsyncResult

    async def source() -> AsyncIterator[int]:
        yield 1
        yield 2

    result = AsyncResult(source())
    assert await anext(result) == 1
    await result.aclose()
    with pytest.raises(RuntimeError, match="closed before its stream finished"):
        await result
    with pytest.raises(StopAsyncIteration):
        await anext(result)  # A read of a closed result just ends.


@pytest.mark.asyncio
async def test_async_result_close_raises_the_sources_close_failure() -> None:
    from grafi.common.models.async_result import AsyncResult

    async def source() -> AsyncIterator[int]:
        try:
            yield 1
            yield 2
        finally:
            raise OSError("release failed")

    result = AsyncResult(source())
    assert await anext(result) == 1
    with pytest.raises(OSError, match="release failed"):
        await result.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_reads_from_other_tasks_still_record_the_responses(
    sequential: bool,
) -> None:
    # Regression: a read may resume the stream in another task (as
    # asyncio.wait_for() does on Python 3.11), whose context has no services
    # bound; the assistant's and workflow's respond events are still written.
    from grafi.common.events.component_events import AssistantRespondEvent
    from grafi.common.events.component_events import WorkflowRespondEvent
    from grafi.topics.expressions.topic_expression import TopicExpr
    from tests_integration.async_execution.support import EchoTool
    from tests_integration.async_execution.support import make_node

    node = make_node(
        "echo",
        EchoTool(),
        TopicExpr(topic=InputTopic(name="input")),
        OutputTopic(name="out"),
    )
    runtime = GrafiRuntime()
    stream = runtime.invoke(
        Assistant(workflow=EventDrivenWorkflow.builder().node(node).build()),
        input_event(),
        sequential,
    )
    outputs = []
    async with asyncio.timeout(5):
        while True:
            try:
                outputs.append(await asyncio.create_task(anext(stream)))
            except StopAsyncIteration:
                break
    assert len(outputs) == 1
    events = await runtime.services.event_store.get_events()
    assert any(isinstance(e, WorkflowRespondEvent) for e in events)
    assert any(isinstance(e, AssistantRespondEvent) for e in events)


@pytest.mark.asyncio
async def test_close_iterator_leaves_a_generator_another_task_is_closing() -> None:
    from grafi.common.async_lifecycle import close_iterator

    release = asyncio.Event()

    async def source() -> AsyncIterator[int]:
        try:
            yield 1
        finally:
            await release.wait()  # Its close is in progress in another task.

    stream = source()
    assert await anext(stream) == 1
    closing = asyncio.create_task(stream.aclose())
    await asyncio.sleep(0)
    # Closing it again would raise "aclose(): asynchronous generator is already
    # running", as when the loop shuts down and closes every open generator.
    await close_iterator(stream)
    release.set()
    async with asyncio.timeout(5):
        await closing
    await close_iterator(stream)  # Closed: closing again does nothing.


def test_isolated_turns_an_exit_from_its_task_into_a_failure() -> None:
    # Regression: an exit raised in the task left the loop through it, and the
    # caller raised it again, leaving the loop twice.
    from grafi.common.async_lifecycle import isolated

    async def exits() -> None:
        raise SystemExit("store shut down")

    loop = asyncio.new_event_loop()
    try:
        caller = loop.create_task(isolated(exits, "Writing"))
        with pytest.raises(SystemExit):  # Through the task, once.
            loop.run_until_complete(caller)
        assert not caller.done()  # Not through the caller's own task.
        with pytest.raises(RuntimeError, match="Writing was interrupted") as raised:
            loop.run_until_complete(caller)
        assert isinstance(raised.value.__cause__, SystemExit)
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_a_cancellation_while_cleaning_up_does_not_replace_an_exit() -> None:
    # Regression: a cancellation raised by a cleanup replaced an exit already
    # propagating, which was then lost.
    from grafi.common.async_lifecycle import best_effort_exit
    from grafi.common.async_lifecycle import cleanup_on_exit

    async def cancelled_cleanup() -> None:
        raise asyncio.CancelledError()

    with pytest.raises(SystemExit) as raised:
        async with cleanup_on_exit(cancelled_cleanup):
            raise SystemExit("exit")
    assert any("CancelledError" in note for note in raised.value.__notes__)

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *exc_info: Any) -> None:
            raise asyncio.CancelledError()

    with pytest.raises(KeyboardInterrupt) as raised_interrupt:
        async with best_effort_exit(Client(), "client"):
            raise KeyboardInterrupt()
    assert any("CancelledError" in note for note in raised_interrupt.value.__notes__)


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="eager task factories need Python 3.12"
)
def test_isolated_runs_its_call_in_its_own_task_under_an_eager_task_factory() -> None:
    # Regression: under an eager task factory the write ran in the caller's
    # frame, so its exit escaped into the caller as is, and the write task's
    # exception was never retrieved.
    import gc

    from grafi.common.async_lifecycle import isolated

    async def exits() -> None:
        raise SystemExit("store shut down")

    logged: list[dict[str, Any]] = []
    loop = asyncio.new_event_loop()
    loop.set_task_factory(asyncio.eager_task_factory)  # type: ignore[attr-defined]
    loop.set_exception_handler(lambda loop, context: logged.append(context))
    try:
        caller = loop.create_task(isolated(exits, "Writing"))
        with pytest.raises(SystemExit):  # From the write's task, once.
            loop.run_until_complete(caller)
        assert not caller.done()  # Not through the caller's own task.
        with pytest.raises(RuntimeError, match="Writing was interrupted"):
            loop.run_until_complete(caller)
    finally:
        loop.close()
    del caller
    gc.collect()
    assert logged == []
