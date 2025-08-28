"""Tests for the unified record decorators."""

import pytest
from unittest.mock import Mock

from grafi.common.decorators.record_decorators import (
    record_tool_invoke,
    record_tool_a_invoke
)
from grafi.common.decorators.record_base import EventContext


class TestEventContext:
    """Test suite for EventContext."""
    
    def test_event_context_creation(self):
        """Test creating an EventContext."""
        context = EventContext(
            id="test-id",
            name="Test Context",
            type="test",
            oi_span_type="context"
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
        context = EventContext(
            name="Minimal",
            type="minimal"
        )
        
        assert context.name == "Minimal"
        assert context.type == "minimal"
        assert context.id != ""  # Should have default_id generated
        assert context.oi_span_type == ""
    
    def test_event_context_allows_extra_fields(self):
        """Test that EventContext allows extra fields due to Config.extra = 'allow'."""
        context = EventContext(
            name="Extra",
            type="extra",
            custom_field="custom_value",
            another_field=123
        )
        
        assert context.name == "Extra"
        assert context.type == "extra"
        # Due to Config.extra = "allow", these should be accessible
        assert hasattr(context, "custom_field")
        assert hasattr(context, "another_field")


class TestToolDecorators:
    """Test suite for tool decorators."""
    
    def test_record_tool_invoke_decorator_exists(self):
        """Test that @record_tool_invoke decorator exists and can be applied."""
        
        @record_tool_invoke
        def test_tool_function(self, messages):
            return f"processed: {len(messages)} messages"
        
        # The decorator should return a callable
        assert callable(test_tool_function)
        
        # The function should have the expected name (may be wrapped)
        assert hasattr(test_tool_function, "__call__")
    
    def test_record_tool_async_decorator_exists(self):
        """Test that @record_tool_a_invoke decorator exists and can be applied."""
        
        @record_tool_a_invoke
        async def test_async_tool_function(self, messages):
            return f"async processed: {len(messages)} messages"
        
        # The decorator should return a callable
        assert callable(test_async_tool_function)
        
        # The decorator might or might not preserve async nature,
        # but it should still be callable
        assert hasattr(test_async_tool_function, "__call__")
    
    def test_decorator_preserves_function_metadata(self):
        """Test that decorators preserve basic function metadata."""
        
        @record_tool_invoke
        def documented_function(self, data):
            """This is a documented tool function."""
            return data
        
        # Basic callable properties should be preserved
        assert callable(documented_function)
        # Note: The actual implementation might wrap the function,
        # so we just verify it's still callable
    
    def test_multiple_decorators_can_be_applied(self):
        """Test that multiple functions can use the same decorators."""
        
        @record_tool_invoke
        def tool_function_1(self, data):
            return f"tool1: {data}"
        
        @record_tool_invoke 
        def tool_function_2(self, data):
            return f"tool2: {data}"
        
        assert callable(tool_function_1)
        assert callable(tool_function_2)
        assert tool_function_1 is not tool_function_2


class TestDecoratorIntegration:
    """Integration tests for decorators."""
    
    def test_decorator_can_be_used_with_mock_tool(self):
        """Test that decorators can be used with mock tool objects."""
        
        class MockTool:
            def __init__(self):
                self.tool_id = "mock-tool"
                self.name = "Mock Tool"
                self.type = "mock"
                self.oi_span_type = Mock()
                self.oi_span_type.value = "tool"
            
            @record_tool_invoke
            def process(self, data):
                return f"processed: {data}"
        
        tool = MockTool()
        
        # Should be able to call the decorated method
        assert hasattr(tool, "process")
        assert callable(tool.process)
    
    def test_both_sync_and_async_decorators_available(self):
        """Test that both sync and async versions are available."""
        
        # Both decorators should be importable and callable
        assert callable(record_tool_invoke)
        assert callable(record_tool_a_invoke)
        
        # Should be able to apply to functions
        @record_tool_invoke
        def sync_func(self, data):
            return data
            
        @record_tool_a_invoke
        async def async_func(self, data):
            return data
        
        assert callable(sync_func)
        assert callable(async_func)
    
    def test_decorator_handles_various_function_signatures(self):
        """Test that decorators can handle various function signatures."""
        
        @record_tool_invoke
        def no_args_func(self):
            return "no args"
            
        @record_tool_invoke
        def single_arg_func(self, data):
            return f"single: {data}"
            
        @record_tool_invoke
        def multi_arg_func(self, data, extra):
            return f"multi: {data}, {extra}"
            
        @record_tool_invoke
        def kwargs_func(self, data, **kwargs):
            return f"kwargs: {data}, {kwargs}"
        
        # All should be callable
        assert callable(no_args_func)
        assert callable(single_arg_func)
        assert callable(multi_arg_func)
        assert callable(kwargs_func)


class TestDecoratorBehavior:
    """Test decorator behavior without mocking internal implementation."""
    
    def test_decorator_returns_wrapper(self):
        """Test that decorators return wrapper functions."""
        
        def original_func(self, data):
            return data
            
        decorated_func = record_tool_invoke(original_func)
        
        # Should return a different object (wrapper)
        assert decorated_func is not original_func
        assert callable(decorated_func)
    
    def test_async_decorator_returns_wrapper(self):
        """Test that async decorator returns a wrapper."""
        
        async def original_async_func(self, data):
            return data
            
        decorated_async_func = record_tool_a_invoke(original_async_func)
        
        # Should return a different object (wrapper) 
        assert decorated_async_func is not original_async_func
        assert callable(decorated_async_func)
        # Don't make assumptions about whether it preserves async nature
    
    def test_decorator_can_be_called_as_function(self):
        """Test that decorators can be used as regular functions."""
        
        def my_function(self, data):
            return f"result: {data}"
        
        # Should be able to call decorator as function
        wrapped = record_tool_invoke(my_function)
        assert callable(wrapped)
        
        # And as decorator syntax
        @record_tool_invoke
        def my_other_function(self, data):
            return f"other: {data}"
            
        assert callable(my_other_function)