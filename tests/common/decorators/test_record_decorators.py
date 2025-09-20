"""Tests for the unified record decorators."""

from grafi.common.decorators.record_base import EventContext
from grafi.common.decorators.record_decorators import record_tool_invoke


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
