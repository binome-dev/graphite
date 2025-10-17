"""
Tests for ToolFactory - Factory class for deserializing tools.
"""

import os

import pytest

from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.impl.duckduckgo_tool import DuckDuckGoTool
from grafi.tools.function_calls.impl.tavily_tool import TavilyTool
from grafi.tools.llms.impl.claude_tool import ClaudeTool
from grafi.tools.llms.impl.deepseek_tool import DeepseekTool
from grafi.tools.llms.impl.gemini_tool import GeminiTool
from grafi.tools.llms.impl.ollama_tool import OllamaTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.impl.openrouter_tool import OpenRouterTool
from grafi.tools.tool import Tool
from grafi.tools.tool_factory import ToolFactory


@pytest.mark.asyncio
async def test_tool_factory_openai_tool():
    """Test factory creates OpenAITool correctly."""
    data = {
        "class": "OpenAITool",
        "tool_id": "test-id",
        "name": "OpenAITool",
        "type": "OpenAITool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "gpt-4o-mini",
        "chat_params": {},
        "is_streaming": False,
        "structured_output": False,
    }

    tool = await ToolFactory.from_dict(data)

    assert isinstance(tool, OpenAITool)
    assert tool.name == "OpenAITool"
    assert tool.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_tool_factory_claude_tool():
    """Test factory creates ClaudeTool correctly."""
    ToolFactory.register_tool_class("ClaudeTool", ClaudeTool)
    data = {
        "class": "ClaudeTool",
        "tool_id": "test-id",
        "name": "ClaudeTool",
        "type": "ClaudeTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 4096,
        "chat_params": {},
        "is_streaming": False,
        "structured_output": False,
    }

    tool = await ToolFactory.from_dict(data)

    assert isinstance(tool, ClaudeTool)
    assert tool.name == "ClaudeTool"
    assert tool.model == "claude-3-5-haiku-20241022"
    assert tool.max_tokens == 4096


@pytest.mark.asyncio
async def test_tool_factory_deepseek_tool():
    """Test factory creates DeepseekTool correctly."""
    ToolFactory.register_tool_class("DeepseekTool", DeepseekTool)
    data = {
        "class": "DeepseekTool",
        "tool_id": "test-id",
        "name": "DeepseekTool",
        "type": "DeepseekTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "chat_params": {},
        "is_streaming": False,
        "structured_output": False,
    }

    tool = await ToolFactory.from_dict(data)

    assert isinstance(tool, DeepseekTool)
    assert tool.name == "DeepseekTool"
    assert tool.base_url == "https://api.deepseek.com"


@pytest.mark.asyncio
async def test_tool_factory_gemini_tool():
    """Test factory creates GeminiTool correctly."""
    ToolFactory.register_tool_class("GeminiTool", GeminiTool)
    data = {
        "class": "GeminiTool",
        "tool_id": "test-id",
        "name": "GeminiTool",
        "type": "GeminiTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "gemini-2.0-flash-lite",
        "chat_params": {},
        "is_streaming": False,
        "structured_output": False,
    }

    tool = await ToolFactory.from_dict(data)

    assert isinstance(tool, GeminiTool)
    assert tool.name == "GeminiTool"
    assert tool.model == "gemini-2.0-flash-lite"


@pytest.mark.asyncio
async def test_tool_factory_ollama_tool():
    """Test factory creates OllamaTool correctly."""
    ToolFactory.register_tool_class("OllamaTool", OllamaTool)
    data = {
        "class": "OllamaTool",
        "tool_id": "test-id",
        "name": "OllamaTool",
        "type": "OllamaTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "qwen3",
        "api_url": "http://localhost:11434",
        "chat_params": {},
        "is_streaming": False,
        "structured_output": False,
    }

    tool = await ToolFactory.from_dict(data)

    assert isinstance(tool, OllamaTool)
    assert tool.name == "OllamaTool"
    assert tool.api_url == "http://localhost:11434"


@pytest.mark.asyncio
async def test_tool_factory_openrouter_tool():
    """Test factory creates OpenRouterTool correctly."""
    ToolFactory.register_tool_class("OpenRouterTool", OpenRouterTool)
    data = {
        "class": "OpenRouterTool",
        "tool_id": "test-id",
        "name": "OpenRouterTool",
        "type": "OpenRouterTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "openrouter/auto",
        "base_url": "https://openrouter.ai/api/v1",
        "extra_headers": {},
        "chat_params": {},
        "is_streaming": False,
        "structured_output": False,
    }

    tool = await ToolFactory.from_dict(data)

    assert isinstance(tool, OpenRouterTool)
    assert tool.name == "OpenRouterTool"
    assert tool.base_url == "https://openrouter.ai/api/v1"


@pytest.mark.asyncio
async def test_tool_factory_duckduckgo_tool():
    """Test factory creates DuckDuckGoTool correctly."""
    ToolFactory.register_tool_class("DuckDuckGoTool", DuckDuckGoTool)
    data = {
        "class": "DuckDuckGoTool",
        "tool_id": "test-id",
        "name": "DuckDuckGoTool",
        "type": "DuckDuckGoTool",
        "oi_span_type": "TOOL",
        "fixed_max_results": 5,
        "timeout": 10,
    }

    tool = await ToolFactory.from_dict(data)

    assert isinstance(tool, DuckDuckGoTool)
    assert tool.name == "DuckDuckGoTool"
    assert tool.timeout == 10


@pytest.mark.asyncio
async def test_tool_factory_tavily_tool():
    """Test factory creates TavilyTool correctly."""
    ToolFactory.register_tool_class("TavilyTool", TavilyTool)
    # Set a dummy API key for test
    os.environ["TAVILY_API_KEY"] = "test_key"

    data = {
        "class": "TavilyTool",
        "tool_id": "test-id",
        "name": "TavilyTool",
        "type": "TavilyTool",
        "oi_span_type": "TOOL",
        "search_depth": "advanced",
        "max_tokens": 6000,
    }

    tool = await ToolFactory.from_dict(data)

    assert isinstance(tool, TavilyTool)
    assert tool.name == "TavilyTool"
    assert tool.search_depth == "advanced"

    # Clean up
    del os.environ["TAVILY_API_KEY"]


@pytest.mark.asyncio
async def test_tool_factory_missing_class():
    """Test factory raises KeyError when class is missing."""
    data = {
        "tool_id": "test-id",
        "name": "SomeTool",
    }

    with pytest.raises(KeyError, match="Missing required key 'class'"):
        await ToolFactory.from_dict(data)


@pytest.mark.asyncio
async def test_tool_factory_unknown_class():
    """Test factory raises ValueError for unknown class."""
    data = {
        "class": "UnknownTool",
        "tool_id": "test-id",
    }

    with pytest.raises(ValueError, match="Unknown tool class: UnknownTool"):
        await ToolFactory.from_dict(data)


@pytest.mark.asyncio
async def test_tool_factory_roundtrip_openai():
    """Test serialization and deserialization roundtrip for OpenAITool."""
    # Create original tool using builder
    original = (
        OpenAITool.builder()
        .name("test_openai")
        .model("gpt-4o-mini")
        .system_message("You are helpful")
        .build()
    )

    # Serialize to dict
    data = original.to_dict()

    # Deserialize back
    restored = await ToolFactory.from_dict(data)

    # Verify
    assert isinstance(restored, OpenAITool)
    assert restored.name == original.name
    assert restored.model == original.model
    assert restored.system_message == original.system_message


@pytest.mark.asyncio
async def test_tool_factory_roundtrip_claude():
    """Test serialization and deserialization roundtrip for ClaudeTool."""
    # Create original tool using builder
    ToolFactory.register_tool_class("ClaudeTool", ClaudeTool)
    original = (
        ClaudeTool.builder()
        .name("test_claude")
        .model("claude-3-5-haiku-20241022")
        .max_tokens(2048)
        .system_message("You are helpful")
        .build()
    )

    # Serialize to dict
    data = original.to_dict()

    # Deserialize back
    restored = await ToolFactory.from_dict(data)

    # Verify
    assert isinstance(restored, ClaudeTool)
    assert restored.name == original.name
    assert restored.model == original.model
    assert restored.max_tokens == original.max_tokens


@pytest.mark.asyncio
async def test_tool_factory_register_custom_class():
    """Test registering a custom tool class."""

    class CustomTool(Tool):
        custom_field: str = "custom"

        @classmethod
        async def from_dict(cls, data):
            return cls(
                tool_id=data.get("tool_id", "default-id"),
                name=data.get("name", "CustomTool"),
                type=data.get("type", "CustomTool"),
                oi_span_type="TOOL",
                custom_field=data.get("custom_field", "custom"),
            )

    # Register the custom class
    ToolFactory.register_tool_class("CustomTool", CustomTool)

    # Test deserialization
    data = {
        "class": "CustomTool",
        "tool_id": "test-id",
        "name": "my_custom",
        "custom_field": "test_value",
    }

    tool = await ToolFactory.from_dict(data)

    assert isinstance(tool, CustomTool)
    assert tool.name == "my_custom"
    assert tool.custom_field == "test_value"

    # Clean up
    ToolFactory.unregister_tool_class("CustomTool")


def test_tool_factory_unregister_class():
    """Test unregistering a tool class."""

    class TempTool(Tool):
        @classmethod
        async def from_dict(cls, data):
            return cls(**data)

    # Register and then unregister
    ToolFactory.register_tool_class("TempTool", TempTool)
    assert ToolFactory.is_registered("TempTool")

    ToolFactory.unregister_tool_class("TempTool")
    assert not ToolFactory.is_registered("TempTool")


def test_tool_factory_is_registered():
    """Test checking if a class is registered."""
    assert ToolFactory.is_registered("OpenAITool")
    assert not ToolFactory.is_registered("NonExistentTool")


def test_tool_factory_get_registered_classes():
    """Test getting registered classes."""
    registered = ToolFactory.get_registered_classes()

    # Check some expected classes are in the registry
    assert "OpenAITool" in registered
    assert "FunctionCallTool" in registered
    assert "FunctionTool" in registered

    # Verify the classes are correct
    assert registered["OpenAITool"] == OpenAITool
    assert registered["FunctionCallTool"] == FunctionCallTool
