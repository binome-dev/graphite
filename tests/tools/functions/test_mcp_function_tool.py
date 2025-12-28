import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
    # Make isinstance check work for TextContent
    content.__class__.__name__ = "TextContent"
    return content


@pytest.fixture
def mock_image_content():
    """Create a mock ImageContent object."""
    content = MagicMock()
    content.data = "base64encodedimage"
    content.type = "image"
    content.__class__.__name__ = "ImageContent"
    return content


@pytest.fixture
def mock_embedded_resource():
    """Create a mock EmbeddedResource object."""
    content = MagicMock()
    content.type = "resource"
    content.resource = MagicMock()
    content.resource.model_dump_json.return_value = '{"uri": "file://test.txt"}'
    content.__class__.__name__ = "EmbeddedResource"
    return content


@pytest.fixture
def mock_prompt():
    """Create a mock Prompt object."""
    prompt = MagicMock()
    prompt.name = "test_prompt"
    return prompt


@pytest.fixture
def mock_resource():
    """Create a mock Resource object."""
    resource = MagicMock()
    resource.uri = MagicMock()
    resource.uri.encoded_string.return_value = "file://test.txt"
    return resource


class TestMCPFunctionToolInitialize:
    @pytest.mark.asyncio
    async def test_initialize_creates_tool_with_function_specs(self, mock_mcp_tool):
        """Test that initialize fetches function specs from MCP server."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.list_resources = AsyncMock(return_value=[])
            mock_client.list_prompts = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            mcp_config = {"mcpServers": {"test": {"command": "test"}}}
            tool = await MCPFunctionTool.initialize(mcp_config=mcp_config)

            assert tool.name == "MCPFunctionTool"
            assert len(tool._function_spec) == 1
            assert tool._function_spec[0].name == "test_tool"
            assert tool._function_spec[0].description == "A test tool"

    @pytest.mark.asyncio
    async def test_initialize_raises_error_without_config(self):
        """Test that initialize raises error when mcp_config is empty."""
        from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

        with pytest.raises(ValueError, match="mcp_config are not set"):
            await MCPFunctionTool.initialize(mcp_config={})


class TestMCPFunctionToolBuilder:
    @pytest.mark.asyncio
    async def test_builder_creates_tool(self, mock_mcp_tool):
        """Test builder pattern for MCPFunctionTool."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.list_resources = AsyncMock(return_value=[])
            mock_client.list_prompts = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await (
                MCPFunctionTool.builder()
                .name("CustomMCPTool")
                .connections({"test_server": {"command": "python", "args": ["-m", "test"]}})
                .build()
            )

            assert tool.name == "CustomMCPTool"
            assert "mcpServers" in tool.mcp_config


class TestMCPFunctionToolInvoke:
    @pytest.mark.asyncio
    async def test_invoke_calls_mcp_tool(
        self, invoke_context, mock_mcp_tool, mock_text_content
    ):
        """Test invoke calls the correct MCP tool and returns response."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            from mcp.types import TextContent as RealTextContent

            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.list_resources = AsyncMock(return_value=[])
            mock_client.list_prompts = AsyncMock(return_value=[])

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
                mcp_config={"mcpServers": {"test": {"command": "test"}}}
            )

            # Create input message with tool call
            from openai.types.chat.chat_completion_message_tool_call import (
                ChatCompletionMessageToolCall,
                Function,
            )

            tool_call = ChatCompletionMessageToolCall(
                id="call_123",
                type="function",
                function=Function(
                    name="test_tool", arguments=json.dumps({"query": "test query"})
                ),
            )
            input_message = Message(role="assistant", content=None, tool_calls=[tool_call])

            messages = []
            async for msg in tool.invoke(invoke_context, [input_message]):
                messages.extend(msg)

            assert len(messages) == 1
            assert "Search result for query" in messages[0].content
            assert messages[0].tool_call_id == "call_123"

    @pytest.mark.asyncio
    async def test_invoke_raises_error_without_tool_calls(
        self, invoke_context, mock_mcp_tool
    ):
        """Test invoke raises error when no tool_calls in message."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.list_resources = AsyncMock(return_value=[])
            mock_client.list_prompts = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await MCPFunctionTool.initialize(
                mcp_config={"mcpServers": {"test": {"command": "test"}}}
            )

            input_message = Message(role="user", content="test")

            with pytest.raises(ValueError, match="Function call is None"):
                async for _ in tool.invoke(invoke_context, [input_message]):
                    pass

    @pytest.mark.asyncio
    async def test_invoke_handles_image_content(self, invoke_context, mock_mcp_tool):
        """Test invoke handles ImageContent response."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            from mcp.types import ImageContent as RealImageContent

            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.list_resources = AsyncMock(return_value=[])
            mock_client.list_prompts = AsyncMock(return_value=[])

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
                mcp_config={"mcpServers": {"test": {"command": "test"}}}
            )

            from openai.types.chat.chat_completion_message_tool_call import (
                ChatCompletionMessageToolCall,
                Function,
            )

            tool_call = ChatCompletionMessageToolCall(
                id="call_456",
                type="function",
                function=Function(name="test_tool", arguments="{}"),
            )
            input_message = Message(role="assistant", content=None, tool_calls=[tool_call])

            messages = []
            async for msg in tool.invoke(invoke_context, [input_message]):
                messages.extend(msg)

            assert len(messages) == 1
            assert messages[0].content == "base64data"


class TestMCPFunctionToolGetPrompt:
    @pytest.mark.asyncio
    async def test_get_prompt_returns_messages(self, mock_mcp_tool, mock_prompt):
        """Test get_prompt fetches and returns prompt messages."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.list_resources = AsyncMock(return_value=[])
            mock_client.list_prompts = AsyncMock(return_value=[mock_prompt])

            # Mock get_prompt response
            prompt_result = MagicMock()
            prompt_message = MagicMock()
            prompt_message.role = "user"
            prompt_message.content = "This is a prompt template"
            prompt_result.messages = [prompt_message]
            mock_client.get_prompt = AsyncMock(return_value=prompt_result)

            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await MCPFunctionTool.initialize(
                mcp_config={"mcpServers": {"test": {"command": "test"}}}
            )

            messages = await tool.get_prompt("test_prompt", arguments={"key": "value"})

            assert len(messages) == 1
            assert messages[0].role == "user"
            assert messages[0].content == "This is a prompt template"

    @pytest.mark.asyncio
    async def test_get_prompt_raises_error_for_unknown_prompt(self, mock_mcp_tool):
        """Test get_prompt raises error for unknown prompt name."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.list_resources = AsyncMock(return_value=[])
            mock_client.list_prompts = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await MCPFunctionTool.initialize(
                mcp_config={"mcpServers": {"test": {"command": "test"}}}
            )

            with pytest.raises(ValueError, match="Prompt 'unknown' not found"):
                await tool.get_prompt("unknown")


class TestMCPFunctionToolGetResources:
    @pytest.mark.asyncio
    async def test_get_resources_returns_resource_content(
        self, mock_mcp_tool, mock_resource
    ):
        """Test get_resources fetches and returns resource content."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.list_resources = AsyncMock(return_value=[mock_resource])
            mock_client.list_prompts = AsyncMock(return_value=[])
            mock_client.read_resource = AsyncMock(
                return_value=[{"content": "resource data"}]
            )

            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await MCPFunctionTool.initialize(
                mcp_config={"mcpServers": {"test": {"command": "test"}}}
            )

            result = await tool.get_resources("file://test.txt")

            assert result == [{"content": "resource data"}]
            mock_client.read_resource.assert_called_once_with("file://test.txt")

    @pytest.mark.asyncio
    async def test_get_resources_raises_error_for_unknown_uri(self, mock_mcp_tool):
        """Test get_resources raises error for unknown resource URI."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.list_resources = AsyncMock(return_value=[])
            mock_client.list_prompts = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await MCPFunctionTool.initialize(
                mcp_config={"mcpServers": {"test": {"command": "test"}}}
            )

            with pytest.raises(ValueError, match="Resource with URI 'file://unknown' not found"):
                await tool.get_resources("file://unknown")


class TestMCPFunctionToolSerialization:
    @pytest.mark.asyncio
    async def test_to_dict(self, mock_mcp_tool, mock_resource, mock_prompt):
        """Test to_dict serializes the tool correctly."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.list_resources = AsyncMock(return_value=[mock_resource])
            mock_client.list_prompts = AsyncMock(return_value=[mock_prompt])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            tool = await MCPFunctionTool.initialize(
                name="TestMCPTool",
                mcp_config={"mcpServers": {"test": {"command": "test"}}},
            )

            result = tool.to_dict()

            assert result["name"] == "TestMCPTool"
            assert result["type"] == "MCPFunctionTool"
            assert "mcp_config" in result
            assert "resources" in result
            assert "prompts" in result

    @pytest.mark.asyncio
    async def test_from_dict(self, mock_mcp_tool):
        """Test from_dict deserializes the tool correctly."""
        with patch(
            "grafi.tools.functions.impl.mcp_function_tool.Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.list_resources = AsyncMock(return_value=[])
            mock_client.list_prompts = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            data = {
                "name": "RestoredMCPTool",
                "type": "MCPFunctionTool",
                "oi_span_type": "TOOL",
                "mcp_config": {"mcpServers": {"test": {"command": "test"}}},
            }

            tool = await MCPFunctionTool.from_dict(data)

            assert isinstance(tool, MCPFunctionTool)
            assert tool.name == "RestoredMCPTool"
