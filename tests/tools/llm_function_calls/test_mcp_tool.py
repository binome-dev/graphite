import json
from typing import Any
from typing import Dict
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
from pydantic_core import PydanticSerializationError

from grafi.common.manifest import ManifestError
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.mcp_tool import MCPTool
from grafi.tools.tool import Tool


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
async def test_get_function_specs_adds_specs(dummy_connections):
    with patch("grafi.tools.function_calls.impl.mcp_tool.Client") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value

        tool = await MCPTool.builder().connections(dummy_connections).build()
        tool.function_specs = []
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "desc"
        mock_tool.inputSchema = {}
        instance.list_tools = AsyncMock(return_value=[mock_tool])
        instance.list_resources = AsyncMock(return_value=[])
        instance.list_prompts = AsyncMock(return_value=[])
        await tool._get_function_specs()
        assert any(fs.name == "test_tool" for fs in tool.function_specs)


@pytest.mark.asyncio
async def test_invoke_text_content(
    dummy_connections, dummy_function_spec, dummy_invoke_context, dummy_input_message
):
    tool = MCPTool(mcp_config={"mcpServers": dummy_connections})
    tool.function_specs = [dummy_function_spec]

    with patch("grafi.tools.function_calls.impl.mcp_tool.Client") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value

        # Create a mock CallToolResult with content attribute
        mock_result = MagicMock()
        mock_result.content = [TextContent(type="text", text="hello")]
        instance.call_tool = AsyncMock(return_value=mock_result)

        result = [
            m async for m in tool.invoke(dummy_invoke_context, dummy_input_message)
        ]
        assert "hello" in result[0][0].content


@pytest.mark.asyncio
async def test_invoke_image_content(
    dummy_connections, dummy_function_spec, dummy_invoke_context, dummy_input_message
):
    tool = MCPTool(mcp_config={"mcpServers": dummy_connections})
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
            m async for m in tool.invoke(dummy_invoke_context, dummy_input_message)
        ]
        assert result[0][0].content == "imgdata"


@pytest.mark.asyncio
async def test_invoke_embedded_resource(
    dummy_connections, dummy_function_spec, dummy_invoke_context, dummy_input_message
):
    tool = MCPTool(mcp_config={"mcpServers": dummy_connections})
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
            m async for m in tool.invoke(dummy_invoke_context, dummy_input_message)
        ]
        assert "Embedded resource" in result[0][0].content


@pytest.mark.asyncio
async def test_invoke_unsupported_content(
    dummy_connections, dummy_function_spec, dummy_invoke_context, dummy_input_message
):
    tool = MCPTool(mcp_config={"mcpServers": dummy_connections})
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
            m async for m in tool.invoke(dummy_invoke_context, dummy_input_message)
        ]
        assert "Unsupported content type" in result[0][0].content


@pytest.mark.asyncio
async def test_invoke_without_tool_calls_yields_nothing(
    dummy_connections, dummy_invoke_context
):
    tool = MCPTool(mcp_config={"mcpServers": dummy_connections})
    message = Message(role="user", content="no calls")
    assert [m async for m in tool.invoke(dummy_invoke_context, [message])] == []


@pytest.mark.asyncio
async def test_get_prompt_and_resources(dummy_connections):
    with patch("grafi.tools.function_calls.impl.mcp_tool.Client") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get_prompt = AsyncMock(
            return_value=MagicMock(messages=[Message(role="user", content="hi")])
        )
        instance.read_resource = AsyncMock(return_value=["res1"])

        tool = await MCPTool.builder().connections(dummy_connections).build()
        tool.prompts = [Prompt(name="prompt1", description="Test prompt")]
        tool.resources = [Resource(uri="user://resource/uri1", name="res1")]

        prompt_msgs = await tool.get_prompt("prompt1")
        assert prompt_msgs[0].content == "hi"
        print(tool.resources)
        res = await tool.get_resources("user://resource/uri1")
        assert res == ["res1"]


# --------------------------------------------------------------------------- #
#  Saving and loading                                                          #
# --------------------------------------------------------------------------- #
MCP_TOOL = "grafi.tools.function_calls.impl.mcp_tool:MCPTool"
CLIENT = "grafi.tools.function_calls.impl.mcp_tool.Client"


def _offering(client_class: MagicMock) -> None:
    """Make the servers the client connects to offer a tool, a resource and a
    prompt."""
    client = client_class.return_value.__aenter__.return_value
    offered = MagicMock()
    offered.name = "get_weather"
    offered.description = "Get weather"
    offered.inputSchema = {
        "type": "object",
        "properties": {"location": {"type": "string"}},
    }
    client.list_tools = AsyncMock(return_value=[offered])
    client.list_resources = AsyncMock(
        return_value=[Resource(uri="user://resource/uri1", name="res1")]
    )
    client.list_prompts = AsyncMock(
        return_value=[Prompt(name="prompt1", description="Test prompt")]
    )


def _server(headers: Dict[str, str]) -> Dict[str, Any]:
    return {
        "mcpServers": {
            "github": {
                "transport": "streamable_http",
                "url": "https://mcp.example/mcp",
                "headers": headers,
            }
        }
    }


@pytest.mark.asyncio
async def test_dump_saves_what_the_servers_offer(dummy_connections):
    with patch(CLIENT) as client_class:
        _offering(client_class)
        tool = await (
            MCPTool.builder().name("TestMCP").connections(dummy_connections).build()
        )

    data = tool.model_dump(mode="json")

    assert data["class"] == MCP_TOOL
    assert data["name"] == "TestMCP"
    assert data["mcp_config"] == {"mcpServers": dummy_connections}
    assert [spec["name"] for spec in data["function_specs"]] == ["get_weather"]
    assert data["functions"] == {}
    assert [resource["uri"] for resource in data["resources"]] == [
        "user://resource/uri1"
    ]
    assert [prompt["name"] for prompt in data["prompts"]] == ["prompt1"]
    json.dumps(data)  # Plain JSON.


@pytest.mark.asyncio
async def test_round_trip_does_not_connect(dummy_connections):
    with patch(CLIENT) as client_class:
        _offering(client_class)
        original = await MCPTool.builder().connections(dummy_connections).build()
        data = original.model_dump(mode="json")
        client_class.reset_mock()

        restored = Tool.model_validate(data)

        client_class.assert_not_called()
    assert type(restored) is MCPTool
    assert restored.tool_id == original.tool_id
    assert restored.mcp_config == original.mcp_config
    assert restored.function_specs == original.function_specs
    assert [resource.uri for resource in restored.resources] == [
        resource.uri for resource in original.resources
    ]
    assert [prompt.name for prompt in restored.prompts] == ["prompt1"]
    assert restored.model_dump() == original.model_dump()
    assert restored.model_dump(mode="json") == data
    # Saving and loading again offers the same, once each.
    again = Tool.model_validate(Tool.model_validate(data).model_dump(mode="json"))
    assert [spec.name for spec in again.function_specs] == ["get_weather"]


def test_load_from_a_manifest_naming_the_class(dummy_connections):
    data = {
        "class": MCP_TOOL,
        "tool_id": "test-id",
        "name": "TestMCP",
        "oi_span_type": "TOOL",
        "mcp_config": {"mcpServers": dummy_connections},
        "function_specs": [
            {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
    }

    with patch(CLIENT) as client_class:
        tool = Tool.model_validate(data)

    client_class.assert_not_called()
    assert isinstance(tool, MCPTool)
    assert tool.tool_id == "test-id"
    assert tool.name == "TestMCP"
    assert tool.mcp_config == {"mcpServers": dummy_connections}
    assert [spec.name for spec in tool.function_specs] == ["get_weather"]


@pytest.mark.parametrize(
    "headers,name",
    [
        ({"Authorization": "Bearer ghp_literal"}, "Authorization"),
        ({"X-API-Key": "literal"}, "X-API-Key"),
    ],
)
def test_a_secret_header_set_to_a_value_is_never_saved(headers, name):
    tool = MCPTool(mcp_config=_server(headers))

    with pytest.raises(
        PydanticSerializationError,
        match=f"ManifestError: .*The MCP server 'github' has '{name}' set to a value",
    ):
        tool.model_dump(mode="json")
    with pytest.raises(ManifestError, match=f"has '{name}' set to a value"):
        tool.to_manifest()


def test_a_secret_environment_variable_set_to_a_value_is_never_saved():
    config = {
        "mcpServers": {
            "local": {"command": "server", "env": {"GITHUB_TOKEN": "ghp_literal"}}
        }
    }

    with pytest.raises(
        PydanticSerializationError,
        match="has 'GITHUB_TOKEN' set to a value",
    ):
        MCPTool(mcp_config=config).model_dump(mode="json")


@pytest.mark.parametrize(
    "server,name",
    [
        # Nested in a setting of the connection.
        (
            {
                "url": "https://mcp.example/mcp",
                "auth": {"oauth": {"client_secret": "literal"}},
            },
            "auth",  # The outer name, which all within it is under.
        ),
        # A URL's query parameter.
        ({"url": "https://mcp.example/mcp?api_key=literal"}, "api_key"),
        # A setting named like a token, as a header.
        (
            {"url": "https://mcp.example/mcp", "headers": {"X-Auth-Token": "t"}},
            "X-Auth-Token",
        ),
        # In a list of settings.
        ({"command": "srv", "args": [{"password": "hunter2"}]}, "password"),
    ],
)
def test_a_secret_anywhere_in_a_connection_is_never_saved(server, name):
    tool = MCPTool(mcp_config={"mcpServers": {"s": server}})

    with pytest.raises(ManifestError, match=f"The MCP server 's' has '{name}'"):
        tool.to_manifest()


def test_a_python_dump_keeps_the_configuration_as_it_is():
    """The secret rules are for JSON: a python-mode dump holds the values."""
    config = _server({"Authorization": "Bearer ghp_literal"})
    tool = MCPTool(mcp_config=config)

    data = tool.model_dump()

    assert data["class"] is MCPTool
    assert data["mcp_config"] == config
    assert MCPTool.model_validate(data).mcp_config == config


def test_a_manifest_reads_only_the_variables_it_is_allowed(dummy_function_spec):
    config = _server({"Authorization": "Bearer ${GITHUB_TOKEN}"})
    manifest = MCPTool(
        mcp_config=config, function_specs=[dummy_function_spec]
    ).to_manifest()

    with pytest.raises(ManifestError, match=r"env=\['GITHUB_TOKEN'\]"):
        MCPTool.from_manifest(manifest)

    with patch(CLIENT) as client_class:
        restored = MCPTool.from_manifest(manifest, env=["GITHUB_TOKEN"])

    client_class.assert_not_called()
    assert restored.mcp_config == config
    assert restored.function_specs == [dummy_function_spec]


@pytest.mark.asyncio
async def test_a_secret_saved_as_a_reference_is_expanded_when_connecting(
    monkeypatch, dummy_function_spec, dummy_invoke_context, dummy_input_message
):
    config = _server(
        {"Authorization": "Bearer ${GITHUB_TOKEN}", "Accept": "application/json"}
    )
    tool = MCPTool(mcp_config=config, function_specs=[dummy_function_spec])
    data = tool.model_dump(mode="json")
    assert data["mcp_config"] == config  # The reference, never the value.
    restored = Tool.model_validate(data)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")

    with patch(CLIENT) as client_class:
        client = client_class.return_value.__aenter__.return_value
        client.call_tool = AsyncMock(
            return_value=MagicMock(content=[TextContent(type="text", text="sunny")])
        )
        [[answer]] = [
            batch
            async for batch in restored.invoke(
                dummy_invoke_context, dummy_input_message
            )
        ]

    assert answer.content == "sunny"
    [connected] = client_class.call_args.args
    assert connected["mcpServers"]["github"]["headers"] == {
        "Authorization": "Bearer ghp_secret",
        "Accept": "application/json",
    }
    assert restored.mcp_config == config  # Expanded for the client only.
