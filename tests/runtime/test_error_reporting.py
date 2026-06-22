"""Tests for correlated error reporting through the decorator + ErrorReporter."""

from types import SimpleNamespace
from typing import Any
from typing import List

import pytest
from opentelemetry.trace import NoOpTracer

from grafi.common.decorators.record_base import _build_error_details
from grafi.common.decorators.record_base import _error_id_for
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.exceptions.tool_exceptions import FunctionCallException
from grafi.common.exceptions.workflow_exceptions import NodeExecutionError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services


class _RecordingReporter:
    def __init__(self) -> None:
        self.calls: List[dict] = []

    def report(self, message, *, level="error"):
        self.calls.append({"message": message, "level": level})


class _RaisingReporter:
    """A misbehaving reporter that raises from report()."""

    def report(self, *args, **kwargs):
        raise RuntimeError("reporter is broken")


class _ExplodingTool:
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
        yield  # pragma: no cover - makes this an async generator


def _ctx() -> InvokeContext:
    return InvokeContext(conversation_id="c", invoke_id="i", assistant_request_id="r")


class TestErrorIdCorrelation:
    def test_error_id_is_inherited_across_rewrapping(self):
        inner = ValueError("root boom")
        first = _error_id_for(inner)
        # A re-wrapped outer exception carries the same correlation id.
        outer = NodeExecutionError(node_name="n", message="node failed", cause=inner)
        assert _error_id_for(outer) == first

    def test_error_id_is_stable_for_one_exception(self):
        exc = ValueError("x")
        assert _error_id_for(exc) == _error_id_for(exc)

    def test_build_error_details_has_correlation_fields(self):
        exc = FunctionCallException(
            tool_name="T",
            function_name="f",
            message="boom",
            invoke_context=_ctx(),
            cause=ValueError("root boom"),
        )
        metadata = SimpleNamespace(id="cid", name="C", type="Tool")
        details = _build_error_details(exc, metadata, _ctx())  # type: ignore[arg-type]
        assert details["error_id"]
        assert details["conversation_id"] == "c"
        assert details["invoke_id"] == "i"
        assert details["assistant_request_id"] == "r"
        assert details["root_error_type"] == "ValueError"
        assert details["root_error_message"] == "root boom"
        assert details["component_name"] == "C"


class TestSingleAuthoritativeEmission:
    @pytest.mark.asyncio
    async def test_one_concise_error_line_with_ids(self):
        reporter = _RecordingReporter()
        services = ExecutionServices(
            event_store=EventStoreInMemory(),
            tracer=NoOpTracer(),
            error_reporter=reporter,
        )
        with bind_services(services):
            with pytest.raises(FunctionCallException):
                async for _ in _ExplodingTool().invoke(
                    _ctx(), [Message(role="user", content="hi")]
                ):
                    pass

        # Exactly one concise ERROR line. It names the failure and carries the
        # lookup ids -- but dumps no traceback (that lives in the event store).
        errors = [c for c in reporter.calls if c["level"] == "error"]
        assert len(errors) == 1
        msg = errors[0]["message"]
        assert "ExplodingTool" in msg
        assert "FunctionCallException" in msg
        assert "error_id=" in msg
        assert "conversation_id=c" in msg
        assert "assistant_request_id=r" in msg
        assert "Traceback" not in msg  # the traceback is not logged


class _FailOnFailedEventStore(EventStoreInMemory):
    """Store that fails to persist *failed* events (but records others)."""

    async def record_event(self, event: Any) -> None:
        if type(event).__name__.endswith("FailedEvent"):
            raise RuntimeError("store down")
        await super().record_event(event)


class TestPreservePrimaryFailure:
    @pytest.mark.asyncio
    async def test_failed_event_persistence_failure_does_not_mask_primary(self):
        reporter = _RecordingReporter()
        services = ExecutionServices(
            event_store=_FailOnFailedEventStore(),
            tracer=NoOpTracer(),
            error_reporter=reporter,
        )
        with bind_services(services):
            # The PRIMARY execution error wins, not the persistence RuntimeError.
            with pytest.raises(FunctionCallException):
                async for _ in _ExplodingTool().invoke(
                    _ctx(), [Message(role="user", content="hi")]
                ):
                    pass

        # The secondary persistence failure is reported as a warning, carrying
        # the error_id and request id so it can still be correlated.
        warnings = [c for c in reporter.calls if c["level"] == "warning"]
        assert len(warnings) == 1
        msg = warnings[0]["message"]
        assert "failed-event NOT persisted" in msg
        assert "error_id=" in msg
        assert "assistant_request_id=r" in msg

    @pytest.mark.asyncio
    async def test_raising_reporter_does_not_mask_primary(self):
        services = ExecutionServices(
            event_store=EventStoreInMemory(),
            tracer=NoOpTracer(),
            error_reporter=_RaisingReporter(),
        )
        with bind_services(services):
            # A reporter that raises must not replace the execution failure.
            with pytest.raises(FunctionCallException):
                async for _ in _ExplodingTool().invoke(
                    _ctx(), [Message(role="user", content="hi")]
                ):
                    pass
