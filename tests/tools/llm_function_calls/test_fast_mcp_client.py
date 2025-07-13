import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastmcp.exceptions import McpError
from mcp.shared.exceptions import ErrorData
from mcp.types import EmbeddedResource
from mcp.types import ImageContent
from mcp.types import TextContent
from mcp.types import TextResourceContents

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.fastmcp_client_tool import FastMCPClient


@pytest.fixture
def mock_fastmcp_client():
    with patch("grafi.tools.function_calls.impl.fastmcp_client_tool.Client") as mock:
        client_instance = AsyncMock()
        mock.return_value = client_instance
        client_instance.__aenter__.return_value = client_instance
        client_instance.__aexit__.return_value = None

        # Configure client methods
        client_instance.is_connected = MagicMock(return_value=True)
        client_instance.list_tools = AsyncMock()
        client_instance.list_resources = AsyncMock()
        client_instance.list_prompts = AsyncMock()
        client_instance.call_tool = AsyncMock()

        yield client_instance


@pytest.fixture
def mock_tool_list():
    tool = MagicMock()
    tool.name = "test_tool"
    tool.description = "Test tool description"
    tool.inputSchema = {"type": "object", "properties": {}}

    return [tool]


@pytest.fixture
def test_client_config():
    return {
        "mcpServers": {
            "test_server": {
                "url": "http://localhost:3000",
                "headers": {"Authorization": "Bearer test_token"},
            }
        }
    }


@pytest.fixture
def test_messages():
    messages = [
        Message(
            role="user",
            content=None,
            tool_calls=[
                {
                    "id": "test_call_id",
                    "type": "function",
                    "function": {
                        "name": "test_function",
                        "arguments": json.dumps({"arg1": "hello"}),
                    },
                }
            ],
        )
    ]
    return messages


@pytest.fixture
def mock_text_content():
    content = TextContent(
        type="text",
        text="Sample response text",
    )
    return content


@pytest.fixture
def mock_image_content():
    content = ImageContent(
        type="image",
        data="base64_image_data",
        mimeType="image/png",
    )
    return content


@pytest.fixture
def mock_embedded_resource():
    # Create a proper TextResourceContents
    resource_contents = TextResourceContents(
        uri="test://resource",
        name="test_resource",
        mimeType="text/plain",
        text="Test resource content",
    )

    content = EmbeddedResource(type="resource", resource=resource_contents)
    return content


class TestFastMCPClient:

    @pytest.mark.asyncio
    async def test_builder_initialization(self):
        builder = FastMCPClient.Builder()
        assert isinstance(builder._tool, FastMCPClient)

    @pytest.mark.asyncio
    async def test_client_config_setting(self, test_client_config):
        builder = FastMCPClient.Builder()
        builder = builder.client_config(test_client_config)
        assert builder._tool.client_config == test_client_config

    @pytest.mark.asyncio
    async def test_build_function_specs(
        self, mock_fastmcp_client, mock_tool_list, test_client_config
    ):
        mock_fastmcp_client.list_tools.return_value = mock_tool_list
        mock_fastmcp_client.list_resources.return_value = []
        mock_fastmcp_client.list_prompts.return_value = []

        builder = FastMCPClient.Builder()
        builder = builder.client_config(test_client_config)

        tool = await builder.a_build()

        assert len(tool.function_specs) == 1
        assert tool.function_specs[0].name == "test_tool"
        assert tool.function_specs[0].description == "Test tool description"

    @pytest.mark.asyncio
    async def test_a_build_no_client_config(self):
        builder = FastMCPClient.Builder()

        with pytest.raises(ValueError, match="Client Config are not set."):
            await builder.a_build()

    @pytest.mark.asyncio
    async def test_a_build_empty_client_config(self):
        builder = FastMCPClient.Builder()
        builder = builder.client_config({})

        with pytest.raises(ValueError, match="Client Config are not set."):
            await builder.a_build()

    @pytest.mark.asyncio
    async def test_a_execute_no_tool_calls(self, test_client_config):
        fastmcp_client = FastMCPClient()
        fastmcp_client.client_config = test_client_config
        context = InvokeContext(
            conversation_id="test_conv",
            invoke_id="test_invoke_id",
            assistant_request_id="test_req",
        )
        messages = [
            Message(
                role="user",
                content="No tool calls here.",
            )
        ]

        with pytest.raises(ValueError, match="Function call is None."):
            async for _ in fastmcp_client.a_execute(context, messages):
                pass

    @pytest.mark.asyncio
    async def test_a_execute_no_client_config(self, test_messages):
        fastmcp_client = FastMCPClient()
        fastmcp_client.function_specs = [
            FunctionSpec(
                name="test_function",
                description="A test function",
                parameters=ParametersSchema(
                    properties={
                        "arg1": ParameterSchema(
                            type="string", description="A test argument"
                        )
                    },
                    required=["arg1"],
                ),
            )
        ]
        context = InvokeContext(
            conversation_id="test_conv",
            invoke_id="test_invoke_id",
            assistant_request_id="test_req",
        )

        with pytest.raises(ValueError, match="No MCP servers defined in the config"):
            async for _ in fastmcp_client.a_execute(context, test_messages):
                pass

    @pytest.mark.asyncio
    async def test_a_execute_client_config_is_none(self, test_messages):
        fastmcp_client = FastMCPClient()
        fastmcp_client.function_specs = [
            FunctionSpec(
                name="test_function",
                description="A test function",
                parameters=ParametersSchema(
                    properties={
                        "arg1": ParameterSchema(
                            type="string", description="A test argument"
                        )
                    },
                    required=["arg1"],
                ),
            )
        ]
        fastmcp_client.client_config = None
        context = InvokeContext(
            conversation_id="test_conv",
            invoke_id="test_invoke_id",
            assistant_request_id="test_req",
        )

        with pytest.raises(ValueError, match="Client Config not set."):
            async for _ in fastmcp_client.a_execute(context, test_messages):
                pass

    @pytest.mark.asyncio
    async def test_a_execute_text_content(
        self, mock_fastmcp_client, test_messages, mock_text_content, test_client_config
    ):
        # Setup
        fastmcp_client = FastMCPClient()
        fastmcp_client.function_specs = [
            FunctionSpec(
                name="test_function",
                description="A test function",
                parameters=ParametersSchema(
                    properties={
                        "arg1": ParameterSchema(
                            type="string", description="A test argument"
                        )
                    },
                    required=["arg1"],
                ),
            )
        ]
        fastmcp_client.client_config = test_client_config
        context = InvokeContext(
            conversation_id="test_conv",
            invoke_id="test_invoke_id",
            assistant_request_id="test_req",
        )

        # Mock call_tool response
        mock_fastmcp_client.call_tool.return_value = [mock_text_content]

        # Execute and collect results
        results = []
        async for result in fastmcp_client.a_execute(context, test_messages):
            results.append(result)

        # Assertions
        assert len(results) == 1
        assert len(results[0]) == 1
        assert results[0][0].tool_call_id == "test_call_id"
        assert "Sample response text" in results[0][0].content
        mock_fastmcp_client.call_tool.assert_called_once_with(
            "test_function", {"arg1": "hello"}
        )

    @pytest.mark.asyncio
    async def test_a_execute_image_content(
        self, mock_fastmcp_client, test_messages, mock_image_content, test_client_config
    ):
        # Setup
        fastmcp_client = FastMCPClient()
        fastmcp_client.function_specs = [
            FunctionSpec(
                name="test_function",
                description="A test function",
                parameters=ParametersSchema(
                    properties={
                        "arg1": ParameterSchema(
                            type="string", description="A test argument"
                        )
                    },
                    required=["arg1"],
                ),
            )
        ]
        fastmcp_client.client_config = test_client_config
        context = InvokeContext(
            conversation_id="test_conv",
            invoke_id="test_invoke_id",
            assistant_request_id="test_req",
        )

        # Mock call_tool response
        mock_fastmcp_client.call_tool.return_value = [mock_image_content]

        # Execute and collect results
        results = []
        async for result in fastmcp_client.a_execute(context, test_messages):
            results.append(result)

        # Verify the image data is returned
        assert len(results) == 1
        assert len(results[0]) == 1
        assert results[0][0].tool_call_id == "test_call_id"
        assert "base64_image_data" in results[0][0].content

    @pytest.mark.asyncio
    async def test_a_execute_embedded_resource(
        self,
        mock_fastmcp_client,
        test_messages,
        mock_embedded_resource,
        test_client_config,
    ):
        # Setup
        fastmcp_client = FastMCPClient()
        fastmcp_client.function_specs = [
            FunctionSpec(
                name="test_function",
                description="A test function",
                parameters=ParametersSchema(
                    properties={
                        "arg1": ParameterSchema(
                            type="string", description="A test argument"
                        )
                    },
                    required=["arg1"],
                ),
            )
        ]
        fastmcp_client.client_config = test_client_config
        context = InvokeContext(
            conversation_id="test_conv",
            invoke_id="test_invoke_id",
            assistant_request_id="test_req",
        )

        # Mock call_tool response
        mock_fastmcp_client.call_tool.return_value = [mock_embedded_resource]

        # Execute and collect results
        results = []
        async for result in fastmcp_client.a_execute(context, test_messages):
            results.append(result)

        # Verify the embedded resource data is returned
        assert len(results) == 1
        assert len(results[0]) == 1
        assert results[0][0].tool_call_id == "test_call_id"
        assert "[Embedded resource:" in results[0][0].content
        assert "test_resource" in results[0][0].content

    @pytest.mark.asyncio
    async def test_a_execute_mcp_error(
        self, mock_fastmcp_client, test_messages, test_client_config
    ):
        # Setup
        fastmcp_client = FastMCPClient()
        fastmcp_client.function_specs = [
            FunctionSpec(
                name="test_function",
                description="A test function",
                parameters=ParametersSchema(
                    properties={
                        "arg1": ParameterSchema(
                            type="string", description="A test argument"
                        )
                    },
                    required=["arg1"],
                ),
            )
        ]
        fastmcp_client.client_config = test_client_config
        context = InvokeContext(
            conversation_id="test_conv",
            invoke_id="test_invoke_id",
            assistant_request_id="test_req",
        )

        # Mock error response
        error_data = ErrorData(code=-1, message="Test MCP error")
        mock_fastmcp_client.call_tool.side_effect = McpError(error_data)

        # Execute and verify error is raised
        with pytest.raises(McpError, match="Test MCP error"):
            async for _ in fastmcp_client.a_execute(context, test_messages):
                pass

    @pytest.mark.asyncio
    async def test_a_execute_function_not_in_specs(
        self, mock_fastmcp_client, test_client_config
    ):
        # Setup
        fastmcp_client = FastMCPClient()
        fastmcp_client.function_specs = [
            FunctionSpec(
                name="different_function",
                description="A different function",
                parameters=ParametersSchema(
                    properties={},
                    required=[],
                ),
            )
        ]
        fastmcp_client.client_config = test_client_config
        context = InvokeContext(
            conversation_id="test_conv",
            invoke_id="test_invoke_id",
            assistant_request_id="test_req",
        )

        messages = [
            Message(
                role="user",
                content=None,
                tool_calls=[
                    {
                        "id": "test_call_id",
                        "type": "function",
                        "function": {
                            "name": "unknown_function",
                            "arguments": json.dumps({"arg1": "hello"}),
                        },
                    }
                ],
            )
        ]

        # Execute and collect results
        results = []
        async for result in fastmcp_client.a_execute(context, messages):
            results.append(result)

        # Should return empty messages since function is not in specs
        assert len(results) == 1
        assert len(results[0]) == 0
        mock_fastmcp_client.call_tool.assert_not_called()

    def test_execute_not_implemented(self, test_client_config):
        fastmcp_client = FastMCPClient()
        fastmcp_client.client_config = test_client_config
        context = InvokeContext(
            conversation_id="test_conv",
            invoke_id="test_invoke_id",
            assistant_request_id="test_req",
        )
        messages = []

        with pytest.raises(
            NotImplementedError,
            match="FastMCPClient does not support synchronous execution",
        ):
            fastmcp_client.execute(context, messages)

    def test_builder_build_not_implemented(self):
        builder = FastMCPClient.Builder()

        with pytest.raises(
            NotImplementedError,
            match="FastMCPClient does not support synchronous execution",
        ):
            builder.build()
