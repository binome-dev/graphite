"""Tests for the unified record decorators."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic_core import to_jsonable_python

from grafi.common.decorators.record_base import ComponentConfig
from grafi.common.decorators.record_base import EventContext
from grafi.common.decorators.record_base import create_async_decorator
from grafi.common.decorators.record_decorators import record_node_invoke
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.event_stores import EventStoreInMemory
from grafi.common.events.component_events import NodeFailedEvent
from grafi.common.events.component_events import ToolFailedEvent
from grafi.common.events.component_events import ToolInvokeEvent
from grafi.common.events.component_events import ToolRespondEvent
from grafi.common.exceptions import EventPersistenceError
from grafi.common.exceptions.tool_exceptions import FunctionCallException
from grafi.common.exceptions.workflow_exceptions import NodeExecutionError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime.deltas import Delta
from grafi.runtime.deltas import deltas_to
from grafi.runtime.deltas import emit_delta
from grafi.runtime.execution_services import ErrorReporter
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services


class _ExplodingTool:
    """Minimal tool-shaped object whose decorated invoke always raises."""

    tool_id = "exploding-tool-id"
    name = "ExplodingTool"
    type = "FunctionCallTool"
    oi_span_type = SimpleNamespace(value="TOOL")

    @record_tool_invoke
    async def invoke(self, invoke_context, input_data):
        raise FunctionCallException(
            tool_name="ExplodingTool",
            function_name="detonate",
            message="function call blew up",
            invoke_context=invoke_context,
            cause=ValueError("root boom"),
        )


class TestFailedEventErrorDetails:
    """The decorator records structured error details and re-raises."""

    @pytest.mark.asyncio
    async def test_failed_event_carries_error_details(self, event_store):
        tool = _ExplodingTool()
        invoke_context = InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        )
        messages = [Message(role="user", content="hi")]

        # The original exception still propagates unchanged.
        with pytest.raises(FunctionCallException) as exc_info:
            await tool.invoke(invoke_context, messages)
        assert exc_info.value.function_name == "detonate"

        events = await event_store.get_events()
        failed = [e for e in events if isinstance(e, ToolFailedEvent)]
        assert len(failed) == 1

        details = failed[0].error_details
        assert details is not None
        assert details["error_type"] == "FunctionCallException"
        assert details["message"] == "function call blew up"
        assert details["component_name"] == "ExplodingTool"
        assert details["component_type"] == "FunctionCallTool"
        assert details["tool_name"] == "ExplodingTool"
        assert details["function_name"] == "detonate"
        assert details["cause"]["error_type"] == "ValueError"

        # A real traceback was captured pointing at the failure site.
        assert details["traceback"]
        assert "detonate" in details["traceback"] or "invoke" in details["traceback"]

        # The persisted payload must be JSON-serializable (JSONB storage).
        json.dumps(details, default=to_jsonable_python)

        # Human-readable string still recorded for backward compatibility.
        assert failed[0].error


class _RecordingSpan:
    """Fake span that remembers whether it had already ended when each
    operation was performed, so a test can prove enrichment happened while the
    span was still recording."""

    def __init__(self) -> None:
        self.ended = False
        self.ends = 0
        self.attr_set_after_end: dict = {}  # attribute key -> ended-state at set
        self.exception_recorded_after_end: list = []
        self.status_set_after_end: list = []

    def set_attribute(self, key, value):
        self.attr_set_after_end[key] = self.ended

    def set_attributes(self, mapping):
        for key in mapping:
            self.attr_set_after_end[key] = self.ended

    def record_exception(self, exc):
        self.exception_recorded_after_end.append(self.ended)

    def set_status(self, status):
        self.status_set_after_end.append(self.ended)

    def is_recording(self) -> bool:
        return not self.ended

    def end(self) -> None:
        # Ending the span must happen AFTER error enrichment, never before.
        self.ended = True
        self.ends += 1


class _RecordingTracer:
    def __init__(self) -> None:
        self.span = _RecordingSpan()

    def start_span(self, _name: str) -> "_RecordingSpan":
        return self.span


class TestSpanErrorEnrichment:
    """Defect #4: failed-span error attributes must be set before span end."""

    @pytest.mark.asyncio
    async def test_error_attributes_recorded_before_span_ends(self):
        tracer = _RecordingTracer()
        services = ExecutionServices(
            event_store=EventStoreInMemory(),
            tracer=tracer,
            error_reporter=ErrorReporter(),
        )
        with bind_services(services):
            tool = _ExplodingTool()
            invoke_context = InvokeContext(
                conversation_id="c",
                invoke_id="i",
                assistant_request_id="r",
            )
            with pytest.raises(FunctionCallException):
                await tool.invoke(invoke_context, [Message(role="user", content="hi")])

        span = tracer.span
        # The span was ended.
        assert span.ended is True
        # Every error attribute was set while the span was still recording.
        assert span.attr_set_after_end.get("error.type") is False
        assert span.attr_set_after_end.get("error_id") is False
        assert span.attr_set_after_end.get("error.details") is False
        # The exception and error status were also recorded before span end.
        assert span.exception_recorded_after_end == [False]
        assert span.status_set_after_end == [False]


_CONTEXT = InvokeContext(conversation_id="c", invoke_id="i", assistant_request_id="r")


class _Node:
    """Minimal node-shaped object that re-wraps its tool's failure."""

    node_id = "node-id"
    name = "SearchNode"
    type = "Node"
    oi_span_type = SimpleNamespace(value="CHAIN")
    _subscribed_topics: dict = {}
    publish_to: list = []

    @record_node_invoke
    async def invoke(self, invoke_context, input_data):
        try:
            await _ExplodingTool().invoke(invoke_context, input_data)
        except FunctionCallException as error:
            raise NodeExecutionError(
                node_name=self.name, message="node failed", cause=error
            ) from error
        yield  # pragma: no cover - makes this an async generator


class _CollectingReporter(ErrorReporter):
    def __init__(self) -> None:
        self.reports: list = []

    def report(self, message: str, level: str = "error") -> None:
        self.reports.append((level, message))


class _FailingStore(EventStoreInMemory):
    """A store that cannot write events of one type."""

    def __init__(self, failing: type) -> None:
        super().__init__()
        self.failing = failing

    async def record_event(self, event) -> None:
        if isinstance(event, self.failing):
            raise ConnectionError("store down")
        await super().record_event(event)


class _QuietTool:
    tool_id = "quiet-tool-id"
    name = "QuietTool"
    type = "FunctionTool"
    oi_span_type = SimpleNamespace(value="TOOL")

    @record_tool_invoke
    async def invoke(self, invoke_context, input_data):
        return [Message(role="assistant", content="done")]


class _FrozenError(Exception):
    """Refuses new attributes, as attrs' frozen exceptions (jsonschema's) do."""

    def __setattr__(self, name, value) -> None:
        if not name.startswith("__"):
            raise AttributeError(f"{name} is frozen")
        super().__setattr__(name, value)


class _FrozenFailureTool(_QuietTool):
    @record_tool_invoke
    async def invoke(self, invoke_context, input_data):
        raise _FrozenError("unresolvable $ref")


@pytest.mark.asyncio
async def test_a_failure_is_logged_once_and_every_layer_records_its_id():
    store, reporter = EventStoreInMemory(), _CollectingReporter()
    with bind_services(ExecutionServices(event_store=store, error_reporter=reporter)):
        with pytest.raises(NodeExecutionError):
            async for _ in _Node().invoke(_CONTEXT, []):
                pass

    assert [level for level, _ in reporter.reports] == ["error"]
    failed = [
        event
        for event in await store.get_events()
        if isinstance(event, (ToolFailedEvent, NodeFailedEvent))
    ]
    assert len(failed) == 2
    error_id = failed[0].error_details["error_id"]
    assert failed[1].error_details["error_id"] == error_id
    assert f"error_id={error_id}" in reporter.reports[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failing", "operation"),
    [(ToolInvokeEvent, "invoke"), (ToolRespondEvent, "respond")],
)
async def test_failing_to_store_a_lifecycle_event_is_the_failure(failing, operation):
    with bind_services(ExecutionServices(event_store=_FailingStore(failing))):
        with pytest.raises(EventPersistenceError) as raised:
            await _QuietTool().invoke(_CONTEXT, [])

    assert raised.value.operation == operation
    assert isinstance(raised.value.__cause__, ConnectionError)


@pytest.mark.asyncio
async def test_a_failure_refusing_its_error_id_is_still_recorded_and_raised():
    store, reporter = EventStoreInMemory(), _CollectingReporter()
    with bind_services(ExecutionServices(event_store=store, error_reporter=reporter)):
        with pytest.raises(_FrozenError):
            await _FrozenFailureTool().invoke(_CONTEXT, [])

    events = await store.get_events()
    assert len(events) == 2 and isinstance(events[-1], ToolFailedEvent)
    assert [level for level, _ in reporter.reports] == ["error"]


class _UnprintableError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("cannot describe the failure")


class _UnprintableFailureTool(_QuietTool):
    @record_tool_invoke
    async def invoke(self, invoke_context, input_data):
        raise _UnprintableError()


@pytest.mark.asyncio
async def test_failing_to_record_a_failure_never_replaces_it():
    reporter = _CollectingReporter()
    with bind_services(ExecutionServices(error_reporter=reporter)):
        with pytest.raises(_UnprintableError) as raised:
            await _UnprintableFailureTool().invoke(_CONTEXT, [])

    assert [level for level, _ in reporter.reports] == ["warning"]
    assert "cannot describe the failure" in raised.value.__notes__[0]


class _QuietNode:
    """Node-shaped: runs the quiet tool inside its own invocation."""

    node_id = "quiet-node"
    name = "QuietNode"
    type = "Node"
    oi_span_type = SimpleNamespace(value="CHAIN")
    _subscribed_topics: dict = {}
    publish_to: list = []

    @record_node_invoke
    async def invoke(self, invoke_context, input_data):
        await _QuietTool().invoke(invoke_context, [])
        return
        yield  # pragma: no cover - makes this an async generator


@pytest.mark.asyncio
async def test_a_stream_runs_with_the_services_where_it_was_made(bound_services):
    # Made under one binding, read under another, as a web framework may read a
    # returned stream: every layer records where the stream was made.
    elsewhere = ExecutionServices()
    with bind_services(elsewhere):
        stream = _QuietNode().invoke(_CONTEXT, [])
    async for _ in stream:
        pass

    assert len(await elsewhere.event_store.get_events()) == 4  # Node and tool.
    assert await bound_services.event_store.get_events() == []


class _StreamingTool(_QuietTool):
    @record_tool_invoke
    async def invoke(self, invoke_context, input_data):
        for text in ("Check", "ing."):
            emit_delta(text)
        return [Message(role="assistant", content="Checking.")]


@pytest.mark.asyncio
async def test_a_streaming_tool_records_its_messages_and_not_its_deltas(
    bound_services,
):
    received = []
    with deltas_to(received.append):
        await _StreamingTool().invoke(_CONTEXT, [])

    assert [delta.content for delta in received] == ["Check", "ing."]
    [respond] = [
        e
        for e in await bound_services.event_store.get_events()
        if isinstance(e, ToolRespondEvent)
    ]
    [message] = respond.output_data
    assert message.content == "Checking."


# A stream of message batches, recorded as a tool's: what it outputs is them all.
_record_stream = create_async_decorator(
    ComponentConfig(
        invoke_event=ToolInvokeEvent,
        respond_event=ToolRespondEvent,
        failed_event=ToolFailedEvent,
        extract_metadata=lambda self: EventContext(
            id=self.tool_id, name=self.name, type=self.type, oi_span_type="TOOL"
        ),
        output_of=lambda batches: [m for batch in batches for m in batch],
    )
)


class _PassingDeltasOn(_QuietTool):
    """Like an assistant streaming its run: its stream carries deltas."""

    @_record_stream
    async def invoke(self, invoke_context, input_data):
        yield Delta("Check")
        yield [Message(role="assistant", content="Checking.")]


@pytest.mark.asyncio
async def test_deltas_passing_through_a_recorded_stream_are_not_recorded(
    bound_services,
):
    items = [item async for item in _PassingDeltasOn().invoke(_CONTEXT, [])]

    assert items[0] == Delta("Check")
    [respond] = [
        e
        for e in await bound_services.event_store.get_events()
        if isinstance(e, ToolRespondEvent)
    ]
    assert [message.content for message in respond.output_data] == ["Checking."]


class _WaitingTool(_QuietTool):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    @record_tool_invoke
    async def invoke(self, invoke_context, input_data):
        self.started.set()
        await asyncio.Event().wait()


def _lifecycle(events) -> list:
    return [type(event).__name__ for event in events]


@pytest.mark.asyncio
async def test_a_tools_invoke_is_recorded_and_its_span_ended_once():
    tracer, store = _RecordingTracer(), EventStoreInMemory()
    with bind_services(ExecutionServices(event_store=store, tracer=tracer)):
        output = await _QuietTool().invoke(_CONTEXT, [])

    assert [message.content for message in output] == ["done"]
    assert _lifecycle(await store.get_events()) == [
        "ToolInvokeEvent",
        "ToolRespondEvent",
    ]
    [respond] = (await store.get_events())[1:]
    assert respond.output_data == output
    assert tracer.span.ends == 1


@pytest.mark.asyncio
async def test_a_failing_tools_invoke_is_recorded_and_its_span_ended_once():
    tracer, store = _RecordingTracer(), EventStoreInMemory()
    with bind_services(ExecutionServices(event_store=store, tracer=tracer)):
        with pytest.raises(FunctionCallException):
            await _ExplodingTool().invoke(_CONTEXT, [])

    assert _lifecycle(await store.get_events()) == [
        "ToolInvokeEvent",
        "ToolFailedEvent",
    ]
    assert tracer.span.ends == 1


@pytest.mark.asyncio
async def test_a_cancelled_tools_invoke_records_no_outcome_and_ends_its_span_once():
    tracer, store = _RecordingTracer(), EventStoreInMemory()
    tool = _WaitingTool()
    with bind_services(ExecutionServices(event_store=store, tracer=tracer)):
        task = asyncio.create_task(tool.invoke(_CONTEXT, []))
    await tool.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Cancelled by its caller: neither a response nor a failure of its own.
    assert _lifecycle(await store.get_events()) == ["ToolInvokeEvent"]
    assert tracer.span.ends == 1


class _NoneTool(_QuietTool):
    @record_tool_invoke
    async def invoke(self, invoke_context, input_data):  # type: ignore[override]
        return None


@pytest.mark.asyncio
async def test_a_tool_returning_other_than_messages_is_its_recorded_failure():
    """Its failure, recorded as any other: not an invalid respond event."""
    tracer, store = _RecordingTracer(), EventStoreInMemory()
    with bind_services(ExecutionServices(event_store=store, tracer=tracer)):
        with pytest.raises(TypeError, match="returns its output as a list of"):
            await _NoneTool().invoke(_CONTEXT, [])

    assert _lifecycle(await store.get_events()) == [
        "ToolInvokeEvent",
        "ToolFailedEvent",
    ]
    assert tracer.span.ends == 1


class _FailingBeforeItStreams(_QuietTool):
    @record_tool_invoke
    def invoke(self, invoke_context, input_data):  # type: ignore[override]
        raise ValueError("no stream")  # Before returning one.


@pytest.mark.asyncio
async def test_a_stream_failing_to_start_is_its_recorded_failure():
    """Its function runs within the invocation, as each step of it does."""
    tracer, store = _RecordingTracer(), EventStoreInMemory()
    with bind_services(ExecutionServices(event_store=store, tracer=tracer)):
        stream = _FailingBeforeItStreams().invoke(_CONTEXT, [])
        with pytest.raises(ValueError, match="no stream"):
            [item async for item in stream]

    assert _lifecycle(await store.get_events()) == [
        "ToolInvokeEvent",
        "ToolFailedEvent",
    ]
    assert tracer.span.ends == 1


@pytest.mark.asyncio
async def test_a_nodes_events_record_its_topics():
    from grafi.nodes.node import Node
    from grafi.tools.functions.function_tool import FunctionTool
    from grafi.topics.topic_impl.input_topic import InputTopic
    from grafi.topics.topic_impl.output_topic import OutputTopic

    node = (
        Node.builder()
        .name("echo")
        .subscribe(InputTopic(name="in"))
        .tool(FunctionTool(function=_echo))
        .publish_to(OutputTopic(name="out"))
        .build()
    )
    store = EventStoreInMemory()
    with bind_services(ExecutionServices(event_store=store)):
        [event async for event in node.invoke(_CONTEXT, [])]

    node_events = [e for e in await store.get_events() if "Node" in type(e).__name__]
    assert node_events
    for event in node_events:
        assert (event.subscribed_topics, event.publish_to_topics) == (["in"], ["out"])


def _echo(messages):
    return "echoed"


@pytest.mark.asyncio
async def test_an_override_calling_super_is_recorded_once_with_its_output():
    """As an LLM's answer is post-processed: the respond event holds what
    the override returns, and the tool is recorded once."""
    from grafi.tools.functions.function_tool import FunctionTool

    def card(_: list) -> str:
        return "card 4111-1111"

    class Redacting(FunctionTool):
        @record_tool_invoke
        async def invoke(self, invoke_context, input_data):
            [answer] = await super().invoke(invoke_context, input_data)
            return [answer.model_copy(update={"content": "card ****"})]

    store = EventStoreInMemory()
    context = InvokeContext(
        conversation_id="c", invoke_id="i", assistant_request_id="r"
    )
    with bind_services(ExecutionServices(event_store=store)):
        await Redacting(function=card).invoke(context, [])

    events = await store.get_events()
    assert [type(e) for e in events] == [ToolInvokeEvent, ToolRespondEvent]
    assert events[1].output_data[0].content == "card ****"


@pytest.mark.asyncio
async def test_a_tool_invoked_again_within_its_invoke_is_recorded_each_time():
    """As a sub-agent sharing its parent's tools reaches the same tool: each
    call is recorded, not only the outer one."""
    from grafi.tools.functions.function_tool import FunctionTool

    calls = []

    async def again(_: list) -> str:
        calls.append(None)
        if len(calls) == 1:
            await tool.invoke(_CONTEXT, [])
        return "done"

    tool = FunctionTool(function=again)
    store = EventStoreInMemory()
    with bind_services(ExecutionServices(event_store=store)):
        await tool.invoke(_CONTEXT, [])

    assert _lifecycle(await store.get_events()) == [
        "ToolInvokeEvent",
        "ToolInvokeEvent",
        "ToolRespondEvent",
        "ToolRespondEvent",
    ]


@pytest.mark.asyncio
async def test_a_streamed_override_calling_super_is_recorded_once():
    """A node's, as an assistant's, decorated override calling
    super().invoke() is recorded once."""
    from grafi.nodes.node import Node
    from grafi.tools.functions.function_tool import FunctionTool
    from grafi.topics.topic_impl.input_topic import InputTopic
    from grafi.topics.topic_impl.output_topic import OutputTopic

    class Logged(Node):
        @record_node_invoke
        async def invoke(self, invoke_context, node_input):
            async for publication in super().invoke(invoke_context, node_input):
                yield publication

    node = (
        Logged.builder()
        .name("echo")
        .subscribe(InputTopic(name="in"))
        .tool(FunctionTool(function=_echo))
        .publish_to(OutputTopic(name="out"))
        .build()
    )
    store = EventStoreInMemory()
    with bind_services(ExecutionServices(event_store=store)):
        [event async for event in node.invoke(_CONTEXT, [])]

    assert [
        name for name in _lifecycle(await store.get_events()) if "Node" in name
    ] == ["NodeInvokeEvent", "NodeRespondEvent"]


@pytest.mark.asyncio
async def test_a_decorator_stacked_on_a_recorded_invoke_keeps_it_recorded():
    """As a retry decorator made with functools.wraps on a recorded invoke."""
    import functools

    from grafi.tools.functions.function_tool import FunctionTool

    def logged(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            return await func(self, *args, **kwargs)

        return wrapper

    class Logged(FunctionTool):
        @logged
        @record_tool_invoke
        async def invoke(self, invoke_context, input_data):
            [answer] = await super().invoke(invoke_context, input_data)
            return [answer.model_copy(update={"content": "logged"})]

    store = EventStoreInMemory()
    with bind_services(ExecutionServices(event_store=store)):
        await Logged(function=_echo).invoke(_CONTEXT, [])

    events = await store.get_events()
    assert _lifecycle(events) == ["ToolInvokeEvent", "ToolRespondEvent"]
    assert events[1].output_data[0].content == "logged"


@pytest.mark.asyncio
async def test_a_decorator_without_wraps_never_leaves_a_call_unrecorded():
    """A decorator hiding the override's mark: the override is recorded."""
    from grafi.tools.functions.function_tool import FunctionTool

    def timed(func):
        async def wrapper(self, *args, **kwargs):
            return await func(self, *args, **kwargs)

        return wrapper

    class Replaces(FunctionTool):
        @timed
        @record_tool_invoke
        async def invoke(self, invoke_context, input_data):
            return [Message(role="assistant", content="own")]

    store = EventStoreInMemory()
    with bind_services(ExecutionServices(event_store=store)):
        await Replaces(function=_echo).invoke(_CONTEXT, [])

    events = await store.get_events()
    assert _lifecycle(events) == ["ToolInvokeEvent", "ToolRespondEvent"]
    assert events[1].output_data[0].content == "own"
