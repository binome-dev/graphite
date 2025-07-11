from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from mcp.types import EmbeddedResource
from mcp.types import ImageContent
from mcp.types import Prompt
from mcp.types import Resource
from mcp.types import TextContent
from mcp.types import TextResourceContents

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.mcp_tool import MCPTool


@pytest.fixture
def dummy_connections():
    # Use SSEConnection type for the dummy connection
    return {
        "default": {
            "transport": "sse",
            "url": "http://localhost:1234",
            "headers": None,
            "timeout": 10.0,
            "sse_read_timeout": 10.0,
            "session_kwargs": None,
            "httpx_client_factory": None,
        }
    }


@pytest.fixture
def dummy_function_spec():
    return FunctionSpec(
        name="get_weather",
        description="Get weather",
        parameters=ParametersSchema(
            type="object",
            properties={"location": ParameterSchema(type="string")},
        ),
    )


@pytest.fixture
def dummy_invoke_context():
    return InvokeContext(
        conversation_id="test_conversation",
        invoke_id="test_invoke",
        assistant_request_id="test_request_id",
    )


@pytest.fixture
def dummy_input_message():
    return [
        Message(
            role="user",
            content="What is the weather in New York?",
            tool_calls=[
                {
                    "id": "test_id",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"location": "London"}',
                    },
                }
            ],
        )
    ]


@pytest.mark.asyncio
async def test_a_get_function_specs_adds_specs(dummy_connections):
    with patch("grafi.tools.function_calls.impl.mcp_tool.Client") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value

        tool = await MCPTool.builder().connections(dummy_connections).a_build()
        tool.function_specs = []
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "desc"
        mock_tool.inputSchema = {}
        instance.list_tools = AsyncMock(return_value=[mock_tool])
        instance.list_resources = AsyncMock(return_value=[])
        instance.list_prompts = AsyncMock(return_value=[])
        await tool._a_get_function_specs()
        assert any(fs.name == "test_tool" for fs in tool.function_specs)


@pytest.mark.asyncio
async def test_a_invoke_text_content(
    dummy_connections, dummy_function_spec, dummy_invoke_context, dummy_input_message
):
    tool = MCPTool(connections=dummy_connections)
    tool.function_specs = [dummy_function_spec]

    with patch("grafi.tools.function_calls.impl.mcp_tool.Client") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value

        # Create a mock CallToolResult with content attribute
        mock_result = MagicMock()
        mock_result.content = [TextContent(type="text", text="hello")]
        instance.call_tool = AsyncMock(return_value=mock_result)

        result = [
            m async for m in tool.a_invoke(dummy_invoke_context, dummy_input_message)
        ]
        assert "hello" in result[0][0].content


@pytest.mark.asyncio
async def test_a_invoke_image_content(
    dummy_connections, dummy_function_spec, dummy_invoke_context, dummy_input_message
):
    tool = MCPTool(connections=dummy_connections)
    tool.function_specs = [dummy_function_spec]

    with patch("grafi.tools.function_calls.impl.mcp_tool.Client") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value

        # Create a mock CallToolResult with content attribute
        mock_result = MagicMock()
        mock_result.content = [
            ImageContent(type="image", data="imgdata", mimeType="image/png")
        ]
        instance.call_tool = AsyncMock(return_value=mock_result)

        result = [
            m async for m in tool.a_invoke(dummy_invoke_context, dummy_input_message)
        ]
        assert result[0][0].content == "imgdata"


@pytest.mark.asyncio
async def test_a_invoke_embedded_resource(
    dummy_connections, dummy_function_spec, dummy_invoke_context, dummy_input_message
):
    tool = MCPTool(connections=dummy_connections)
    tool.function_specs = [dummy_function_spec]

    with patch("grafi.tools.function_calls.impl.mcp_tool.Client") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value

        # Create a mock CallToolResult with content attribute
        mock_result = MagicMock()
        mock_result.content = [
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri="user://resource/123",
                    text="Embedded resource content",
                    mimeType="text/plain",
                ),
            )
        ]
        instance.call_tool = AsyncMock(return_value=mock_result)

        result = [
            m async for m in tool.a_invoke(dummy_invoke_context, dummy_input_message)
        ]
        assert "Embedded resource" in result[0][0].content


@pytest.mark.asyncio
async def test_a_invoke_unsupported_content(
    dummy_connections, dummy_function_spec, dummy_invoke_context, dummy_input_message
):
    tool = MCPTool(connections=dummy_connections)
    tool.function_specs = [dummy_function_spec]

    class DummyOtherContent:
        type = "other"

    with patch("grafi.tools.function_calls.impl.mcp_tool.Client") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value

        # Create a mock CallToolResult with content attribute
        mock_result = MagicMock()
        mock_result.content = [DummyOtherContent()]
        instance.call_tool = AsyncMock(return_value=mock_result)

        result = [
            m async for m in tool.a_invoke(dummy_invoke_context, dummy_input_message)
        ]
        assert "Unsupported content type" in result[0][0].content


@pytest.mark.asyncio
async def test_a_invoke_no_tool_calls(dummy_connections, dummy_invoke_context):
    tool = MCPTool(connections=dummy_connections)

    class DummyInputMessage:
        tool_calls = None

    with pytest.raises(ValueError):
        async for _ in tool.a_invoke(dummy_invoke_context, [DummyInputMessage()]):
            pass


@pytest.mark.asyncio
async def test_get_prompt_and_resources(dummy_connections):
    with patch("grafi.tools.function_calls.impl.mcp_tool.Client") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_prompt = AsyncMock(
            return_value=MagicMock(messages=[Message(role="user", content="hi")])
        )
        instance.read_resource = AsyncMock(return_value=["res1"])

        tool = await MCPTool.builder().connections(dummy_connections).a_build()
        tool.prompts = [Prompt(name="prompt1", description="Test prompt")]
        tool.resources = [Resource(uri="user://resource/uri1", name="res1")]

        prompt_msgs = await tool.get_prompt("prompt1")
        assert prompt_msgs[0].content == "hi"
        print(tool.resources)
        res = await tool.get_resources("user://resource/uri1")
        assert res == ["res1"]
