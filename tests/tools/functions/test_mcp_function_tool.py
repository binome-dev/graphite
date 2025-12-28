import json
import uuid
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


@pytest.fixture
def invoke_context():
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


@pytest.fixture
def mock_mcp_tool():
    """Create a mock MCP Tool object."""
    tool = MagicMock()
    tool.name = "test_tool"
    tool.description = "A test tool"
    tool.inputSchema = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query"}},
        "required": ["query"],
    }
    return tool


@pytest.fixture
def mock_text_content():
    """Create a mock TextContent object."""
    content = MagicMock()
    content.text = "Test response text"
    content.__class__.__name__ = "TextContent"
    return content


class TestMCPFunctionToolInitialize:
    @pytest.mark.asyncio
    async def test_initialize_creates_tool_with_function_spec(self, mock_mcp_tool):
        """Test that initialize fetches function spec from MCP server."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            mcp_config = {"mcpServers": {"test": {"command": "test"}}}
            tool = await MCPFunctionTool.initialize(
                mcp_config=mcp_config, function_name="test_tool"
            )

            assert tool.name == "MCPFunctionTool"
            assert tool.function_name == "test_tool"
            assert tool._function_spec is not None
            assert tool._function_spec.name == "test_tool"
            assert tool._function_spec.description == "A test tool"

    @pytest.mark.asyncio
    async def test_initialize_without_function_name_uses_first_tool(
        self, mock_mcp_tool
    ):
        """Test that initialize uses first available tool when function_name not specified."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            mcp_config = {"mcpServers": {"test": {"command": "test"}}}
            tool = await MCPFunctionTool.initialize(mcp_config=mcp_config)

            assert tool._function_spec.name == "test_tool"

    @pytest.mark.asyncio
    async def test_initialize_raises_error_without_config(self):
        """Test that initialize raises error when mcp_config is empty."""
        from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

        with pytest.raises(ValueError, match="mcp_config are not set"):
            await MCPFunctionTool.initialize(mcp_config={})

    @pytest.mark.asyncio
    async def test_initialize_raises_error_when_tool_not_found(self, mock_mcp_tool):
        """Test that initialize raises error when specified function_name not found."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            mcp_config = {"mcpServers": {"test": {"command": "test"}}}
            with pytest.raises(ValueError, match="Tool 'nonexistent' not found"):
                await MCPFunctionTool.initialize(
                    mcp_config=mcp_config, function_name="nonexistent"
                )

    @pytest.mark.asyncio
    async def test_initialize_raises_error_when_no_tools_available(self):
        """Test that initialize raises error when no tools available from server."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            mcp_config = {"mcpServers": {"test": {"command": "test"}}}
            with pytest.raises(ValueError, match="No tools available from MCP server"):
                await MCPFunctionTool.initialize(mcp_config=mcp_config)


class TestMCPFunctionToolBuilder:
    @pytest.mark.asyncio
    async def test_builder_creates_tool(self, mock_mcp_tool):
        """Test builder pattern for MCPFunctionTool."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await (
                MCPFunctionTool.builder()
                .name("CustomMCPTool")
                .connections(
                    {"test_server": {"command": "python", "args": ["-m", "test"]}}
                )
                .function_name("test_tool")
                .build()
            )

            assert tool.name == "CustomMCPTool"
            assert tool.function_name == "test_tool"
            assert "mcpServers" in tool.mcp_config


class TestMCPFunctionToolInvokeMcpFunction:
    @pytest.mark.asyncio
    async def test_invoke_mcp_function_calls_tool(self, mock_mcp_tool):
        """Test invoke_mcp_function calls the correct MCP tool and returns response."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            from mcp.types import TextContent as RealTextContent

            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])

            # Mock call_tool response
            call_result = MagicMock()
            text_content = RealTextContent(type="text", text="Search result for query")
            call_result.content = [text_content]
            mock_client.call_tool = AsyncMock(return_value=call_result)

            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await MCPFunctionTool.initialize(
                mcp_config={"mcpServers": {"test": {"command": "test"}}},
                function_name="test_tool",
            )

            # Create input message with tool call and content containing kwargs
            from openai.types.chat.chat_completion_message_tool_call import (
                ChatCompletionMessageToolCall,
            )
            from openai.types.chat.chat_completion_message_tool_call import Function

            tool_call = ChatCompletionMessageToolCall(
                id="call_123",
                type="function",
                function=Function(name="test_tool", arguments="{}"),
            )
            input_message = Message(
                role="assistant",
                content=json.dumps({"query": "test query"}),
                tool_calls=[tool_call],
            )

            results = []
            async for result in tool.invoke_mcp_function([input_message]):
                results.append(result)

            assert len(results) == 1
            assert "Search result for query" in results[0]

    @pytest.mark.asyncio
    async def test_invoke_mcp_function_raises_error_without_tool_calls(
        self, mock_mcp_tool
    ):
        """Test invoke_mcp_function raises error when no tool_calls in message."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await MCPFunctionTool.initialize(
                mcp_config={"mcpServers": {"test": {"command": "test"}}},
                function_name="test_tool",
            )

            input_message = Message(role="user", content="{}")

            with pytest.raises(ValueError, match="Function call is None"):
                async for _ in tool.invoke_mcp_function([input_message]):
                    pass

    @pytest.mark.asyncio
    async def test_invoke_mcp_function_handles_image_content(self, mock_mcp_tool):
        """Test invoke_mcp_function handles ImageContent response."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            from mcp.types import ImageContent as RealImageContent

            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])

            # Mock call_tool response with image content
            call_result = MagicMock()
            image_content = RealImageContent(
                type="image", data="base64data", mimeType="image/png"
            )
            call_result.content = [image_content]
            mock_client.call_tool = AsyncMock(return_value=call_result)

            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await MCPFunctionTool.initialize(
                mcp_config={"mcpServers": {"test": {"command": "test"}}},
                function_name="test_tool",
            )

            from openai.types.chat.chat_completion_message_tool_call import (
                ChatCompletionMessageToolCall,
            )
            from openai.types.chat.chat_completion_message_tool_call import Function

            tool_call = ChatCompletionMessageToolCall(
                id="call_456",
                type="function",
                function=Function(name="test_tool", arguments="{}"),
            )
            input_message = Message(
                role="assistant", content="{}", tool_calls=[tool_call]
            )

            results = []
            async for result in tool.invoke_mcp_function([input_message]):
                results.append(result)

            assert len(results) == 1
            assert results[0] == "base64data"

    @pytest.mark.asyncio
    async def test_invoke_mcp_function_handles_embedded_resource(self, mock_mcp_tool):
        """Test invoke_mcp_function handles EmbeddedResource response."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            from mcp.types import EmbeddedResource as RealEmbeddedResource
            from mcp.types import TextResourceContents

            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])

            # Mock call_tool response with embedded resource
            call_result = MagicMock()
            resource_contents = TextResourceContents(
                uri="file://test.txt", mimeType="text/plain", text="resource content"
            )
            embedded_resource = RealEmbeddedResource(
                type="resource", resource=resource_contents
            )
            call_result.content = [embedded_resource]
            mock_client.call_tool = AsyncMock(return_value=call_result)

            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await MCPFunctionTool.initialize(
                mcp_config={"mcpServers": {"test": {"command": "test"}}},
                function_name="test_tool",
            )

            from openai.types.chat.chat_completion_message_tool_call import (
                ChatCompletionMessageToolCall,
            )
            from openai.types.chat.chat_completion_message_tool_call import Function

            tool_call = ChatCompletionMessageToolCall(
                id="call_789",
                type="function",
                function=Function(name="test_tool", arguments="{}"),
            )
            input_message = Message(
                role="assistant", content="{}", tool_calls=[tool_call]
            )

            results = []
            async for result in tool.invoke_mcp_function([input_message]):
                results.append(result)

            assert len(results) == 1
            assert "[Embedded resource:" in results[0]


class TestMCPFunctionToolSerialization:
    @pytest.mark.asyncio
    async def test_to_dict(self, mock_mcp_tool):
        """Test to_dict serializes the tool correctly."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await MCPFunctionTool.initialize(
                name="TestMCPTool",
                mcp_config={"mcpServers": {"test": {"command": "test"}}},
                function_name="test_tool",
            )

            result = tool.to_dict()

            assert result["name"] == "TestMCPTool"
            assert result["type"] == "MCPFunctionTool"
            assert "mcp_config" in result
            assert result["function_name"] == "test_tool"

    @pytest.mark.asyncio
    async def test_from_dict(self, mock_mcp_tool):
        """Test from_dict deserializes the tool correctly."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            data = {
                "name": "RestoredMCPTool",
                "type": "MCPFunctionTool",
                "oi_span_type": "TOOL",
                "mcp_config": {"mcpServers": {"test": {"command": "test"}}},
                "function_name": "test_tool",
            }

            tool = await MCPFunctionTool.from_dict(data)

            assert isinstance(tool, MCPFunctionTool)
            assert tool.name == "RestoredMCPTool"
            assert tool.function_name == "test_tool"

    @pytest.mark.asyncio
    async def test_to_dict_from_dict_roundtrip(self, mock_mcp_tool):
        """Test that to_dict and from_dict are consistent."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            original = await MCPFunctionTool.initialize(
                name="RoundtripTool",
                mcp_config={"mcpServers": {"test": {"command": "test"}}},
                function_name="test_tool",
            )

            data = original.to_dict()
            restored = await MCPFunctionTool.from_dict(data)

            assert restored.name == original.name
            assert restored.function_name == original.function_name
            assert restored.mcp_config == original.mcp_config
