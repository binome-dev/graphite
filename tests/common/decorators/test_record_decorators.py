"""Tests for the unified record decorators."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic_core import to_jsonable_python

from grafi.common.containers.container import container
from grafi.common.decorators.record_base import _TRACEBACK_LOGGED_ATTR
from grafi.common.decorators.record_base import EventContext
from grafi.common.decorators.record_base import _traceback_already_logged
from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.event_stores import EventStoreInMemory
from grafi.common.events.component_events import ToolFailedEvent
from grafi.common.exceptions.tool_exceptions import FunctionCallException
from grafi.common.exceptions.workflow_exceptions import NodeExecutionError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


@pytest.fixture
def isolated_container():
    """Register an isolated in-memory store and a no-op tracer, then restore.

    Using a mock tracer avoids the live ``setup_tracing`` path (a socket probe to
    localhost:4317 and possible global instrumentation side effects). The previous
    container state is restored so the global singleton does not leak across tests.
    """
    prev_store = container._event_store
    prev_tracer = container._tracer
    store = EventStoreInMemory()
    container.register_event_store(store)
    container.register_tracer(MagicMock())
    try:
        yield store
    finally:
        container._event_store = prev_store
        container._tracer = prev_tracer


class TestEventContext:
    """Test suite for EventContext."""

    def test_event_context_creation(self):
        """Test creating an EventContext."""
        context = EventContext(
            id="test-id", name="Test Context", type="test", oi_span_type="context"
        )

        assert context.id == "test-id"
        assert context.name == "Test Context"
        assert context.type == "test"
        assert context.oi_span_type == "context"

    def test_event_context_with_defaults(self):
        """Test EventContext with default values."""
        context = EventContext()

        # Should have default values
        assert context.id != ""  # Should have default_id generated
        assert context.name == ""
        assert context.type == ""
        assert context.oi_span_type == ""

    def test_event_context_with_minimal_fields(self):
        """Test EventContext with minimal required fields."""
        context = EventContext(name="Minimal", type="minimal")

        assert context.name == "Minimal"
        assert context.type == "minimal"
        assert context.id != ""  # Should have default_id generated
        assert context.oi_span_type == ""

    def test_event_context_allows_extra_fields(self):
        """Test that EventContext allows extra fields due to Config.extra = 'allow'."""
        context = EventContext(
            name="Extra", type="extra", custom_field="custom_value", another_field=123
        )

        assert context.name == "Extra"
        assert context.type == "extra"
        # Due to Config.extra = "allow", these should be accessible
        assert hasattr(context, "custom_field")
        assert hasattr(context, "another_field")


class TestToolDecorators:
    """Test suite for tool decorators."""

    def test_record_tool_async_decorator_exists(self):
        """Test that @record_tool_invoke decorator exists and can be applied."""

        @record_tool_invoke
        async def test_async_tool_function(self, messages):
            return f"async processed: {len(messages)} messages"

        # The decorator should return a callable
        assert callable(test_async_tool_function)

        # The decorator might or might not preserve async nature,
        # but it should still be callable
        assert hasattr(test_async_tool_function, "__call__")


class TestDecoratorBehavior:
    """Test decorator behavior without mocking internal implementation."""

    def test_async_decorator_returns_wrapper(self):
        """Test that async decorator returns a wrapper."""

        async def original_async_func(self, data):
            return data

        decorated_async_func = record_tool_invoke(original_async_func)

        # Should return a different object (wrapper)
        assert decorated_async_func is not original_async_func
        assert callable(decorated_async_func)
        # Don't make assumptions about whether it preserves async nature


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
        yield  # pragma: no cover - makes this an async generator


class TestFailedEventErrorDetails:
    """The decorator records structured error details and re-raises."""

    @pytest.mark.asyncio
    async def test_failed_event_carries_error_details(self, isolated_container):
        event_store = isolated_container

        tool = _ExplodingTool()
        invoke_context = InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        )
        messages = [Message(role="user", content="hi")]

        # The original exception still propagates unchanged.
        with pytest.raises(FunctionCallException) as exc_info:
            async for _ in tool.invoke(invoke_context, messages):
                pass
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


class TestTracebackDedup:
    """The full traceback is logged once even after the error is re-wrapped."""

    def test_flag_survives_rewrapping(self):
        inner = ValueError("root boom")
        # The innermost decorator marks the exception it caught.
        setattr(inner, _TRACEBACK_LOGGED_ATTR, True)

        # The workflow re-wraps it into a new exception with cause=inner.
        outer = NodeExecutionError(
            node_name="SearchNode", message="node failed", cause=inner
        )

        # An outer decorator must still see that the traceback was already logged.
        assert _traceback_already_logged(outer) is True

    def test_fresh_chain_not_yet_logged(self):
        inner = ValueError("root boom")
        outer = NodeExecutionError(
            node_name="SearchNode", message="node failed", cause=inner
        )
        assert _traceback_already_logged(outer) is False
