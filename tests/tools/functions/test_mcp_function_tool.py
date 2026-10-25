import json
import uuid
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from mcp.types import TextContent
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool
from grafi.tools.tool import Tool


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
        with patch("fastmcp.Client") as mock_client_class:
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
            mock_client.list_tools.assert_awaited_once()  # It checked the server.

    @pytest.mark.asyncio
    async def test_initialize_without_function_name_uses_first_tool(
        self, mock_mcp_tool
    ):
        """Test that initialize uses first available tool when function_name not specified."""
        with patch("fastmcp.Client") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(return_value=[mock_mcp_tool])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

            mcp_config = {"mcpServers": {"test": {"command": "test"}}}
            tool = await MCPFunctionTool.initialize(mcp_config=mcp_config)

            assert tool.function_name == "test_tool"

    @pytest.mark.asyncio
    async def test_initialize_raises_error_without_config(self):
        """Test that initialize raises error when mcp_config is empty."""
        from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

        with pytest.raises(ValueError, match="has no servers"):
            await MCPFunctionTool.initialize(mcp_config={})

    @pytest.mark.asyncio
    async def test_initialize_raises_error_when_tool_not_found(self, mock_mcp_tool):
        """Test that initialize raises error when specified function_name not found."""
        with patch("fastmcp.Client") as mock_client_class:
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
        with patch("fastmcp.Client") as mock_client_class:
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
        with patch("fastmcp.Client") as mock_client_class:
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
        with patch("fastmcp.Client") as mock_client_class:
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

            input_message = Message(
                role="assistant",
                content=json.dumps({"query": "test query"}),
            )

            results = [await tool.invoke_mcp_function([input_message])]

            assert len(results) == 1
            assert "Search result for query" in results[0]

    @pytest.mark.asyncio
    async def test_invoke_mcp_function_handles_image_content(self, mock_mcp_tool):
        """Test invoke_mcp_function handles ImageContent response."""
        with patch("fastmcp.Client") as mock_client_class:
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

            input_message = Message(role="assistant", content="{}")

            results = [await tool.invoke_mcp_function([input_message])]

            assert len(results) == 1
            assert results[0] == "base64data"

    @pytest.mark.asyncio
    async def test_invoke_mcp_function_handles_embedded_resource(self, mock_mcp_tool):
        """Test invoke_mcp_function handles EmbeddedResource response."""
        with patch("fastmcp.Client") as mock_client_class:
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

            input_message = Message(role="assistant", content="{}")

            results = [await tool.invoke_mcp_function([input_message])]

            assert len(results) == 1
            assert "[Embedded resource:" in results[0]


MCP_FUNCTION_TOOL = "grafi.tools.functions.impl.mcp_function_tool:MCPFunctionTool"
CLIENT = "fastmcp.Client"
CONFIG = {"mcpServers": {"test": {"command": "test"}}}


def _client_offering(mock_client_class: MagicMock, *tools: Any) -> AsyncMock:
    """The client MCPFunctionTool connects with, listing ``tools``."""
    mock_client = AsyncMock()
    mock_client.list_tools = AsyncMock(return_value=list(tools))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client_class.return_value = mock_client
    return mock_client


class TestMCPFunctionToolSerialization:
    @pytest.mark.asyncio
    async def test_dump(self, mock_mcp_tool):
        """The server and the tool's name are saved; the function is not."""
        with patch(CLIENT) as mock_client_class:
            _client_offering(mock_client_class, mock_mcp_tool)
            tool = await MCPFunctionTool.initialize(
                name="TestMCPTool", mcp_config=CONFIG, function_name="test_tool"
            )

        assert tool.model_dump(mode="json") == {
            "class": MCP_FUNCTION_TOOL,
            "tool_id": tool.tool_id,
            "name": "TestMCPTool",
            "type": "MCPFunctionTool",
            "oi_span_type": "TOOL",
            "role": "assistant",
            "mcp_config": CONFIG,
            "function_name": "test_tool",
        }

    def test_load_does_not_connect(self):
        data = {
            "class": MCP_FUNCTION_TOOL,
            "tool_id": "test-id",
            "name": "RestoredMCPTool",
            "oi_span_type": "TOOL",
            "mcp_config": CONFIG,
            "function_name": "test_tool",
        }

        with patch(CLIENT) as mock_client_class:
            tool = Tool.model_validate(data)

        mock_client_class.assert_not_called()
        assert isinstance(tool, MCPFunctionTool)
        assert tool.tool_id == "test-id"
        assert tool.name == "RestoredMCPTool"
        assert tool.mcp_config == CONFIG
        assert tool.function_name == "test_tool"
        assert tool._function() == tool.invoke_mcp_function

    @pytest.mark.asyncio
    async def test_round_trip(self, mock_mcp_tool):
        with patch(CLIENT) as mock_client_class:
            mock_client = _client_offering(mock_client_class, mock_mcp_tool)
            original = await MCPFunctionTool.initialize(
                name="RoundtripTool", mcp_config=CONFIG
            )
            data = original.model_dump(mode="json")
            mock_client_class.reset_mock()

            restored = Tool.model_validate(data)

            mock_client_class.assert_not_called()
            assert type(restored) is MCPFunctionTool
            assert restored.tool_id == original.tool_id
            assert restored.name == "RoundtripTool"
            assert restored.function_name == "test_tool"  # The server's first.
            assert restored.mcp_config == original.mcp_config
            assert restored._function() == restored.invoke_mcp_function
            assert restored.model_dump(mode="json") == data
            # It calls the tool it was saved with.
            mock_client.call_tool = AsyncMock(
                return_value=MagicMock(content=[TextContent(type="text", text="ok")])
            )
            answer = await restored._function()(
                [Message(role="user", content='{"query": "q"}')]
            )

        assert answer == "ok"
        mock_client.call_tool.assert_awaited_once_with("test_tool", {"query": "q"})

    def test_a_secret_environment_variable_set_to_a_value_is_never_saved(self):
        tool = MCPFunctionTool(
            mcp_config={
                "mcpServers": {"s": {"command": "srv", "env": {"API_KEY": "literal"}}}
            },
            function_name="search",
        )

        with pytest.raises(
            PydanticSerializationError,
            match="ManifestError: .*The MCP server 's' has 'API_KEY' set to a value",
        ):
            tool.model_dump(mode="json")

    def test_a_secret_saved_as_a_reference_is_kept(self):
        config = {
            "mcpServers": {
                "s": {
                    "url": "https://mcp.example/mcp",
                    "headers": {"Authorization": "Bearer ${SEARCH_TOKEN}"},
                    "env": {"API_KEY": "${SEARCH_API_KEY}"},
                }
            }
        }
        tool = MCPFunctionTool(mcp_config=config, function_name="search")

        data = tool.model_dump(mode="json")

        assert data["mcp_config"] == config
        loaded = Tool.from_manifest(
            tool.to_manifest(), allow_env=["SEARCH_TOKEN", "SEARCH_API_KEY"]
        )
        assert loaded.mcp_config == config


def test_a_copy_calls_its_own_server_tool():
    """It has no function of its own to copy: it calls the tool it names."""
    from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool

    tool = MCPFunctionTool(mcp_config=CONFIG, function_name="echo")
    copy = tool.model_copy(update={"function_name": "reverse"})

    assert copy._function().__self__ is copy


def test_a_function_given_it_is_refused():
    """It calls its server's tool, so a function given it would be ignored."""
    with pytest.raises(ValidationError, match="function"):
        MCPFunctionTool(mcp_config=CONFIG, function_name="echo", function=print)

    tool = MCPFunctionTool(mcp_config=CONFIG, function_name="echo")
    assert Tool.from_manifest(tool.to_manifest()).function_name == "echo"
