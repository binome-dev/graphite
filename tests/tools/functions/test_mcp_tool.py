import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpec, ParameterSchema, ParametersSchema
from grafi.common.models.message import Message
from grafi.tools.functions.impl.mcp_tool import MCPTool
from mcp.types import TextContent, ImageContent

@pytest.fixture
def mock_stdio_client():
    with patch("grafi.tools.functions.impl.mcp_tool.stdio_client") as mock:
        context_manager = AsyncMock()
        mock.return_value = context_manager
        context_manager.__aenter__.return_value = (AsyncMock(), AsyncMock())
        yield mock


@pytest.fixture
def mock_client_session():
    with patch("grafi.tools.functions.impl.mcp_tool.ClientSession") as mock:
        session = AsyncMock()
        mock.return_value = session
        session.__aenter__.return_value = session
        
        # Configure session methods
        session.initialize = AsyncMock()
        session.list_prompts = AsyncMock()
        session.list_resources = AsyncMock()
        session.list_tools = AsyncMock()
        session.call_tool = AsyncMock()
        
        yield session


@pytest.fixture
def mock_tool_list():
    tool = MagicMock()
    tool.name = "test_tool"
    tool.description = "Test tool description"
    tool.inputSchema = {"type": "object", "properties": {}}
    
    tools_list = MagicMock()
    tools_list.tools = [tool]
    return tools_list


@pytest.fixture
def test_message():
    
    message = Message(
        role="user",
        content=None,
        tool_calls=[{
                "id": "test_call_id",
                "type": "function",
                "function": {
                    "name": "test_function",
                    "arguments": json.dumps({"arg1": "hello"}),
                },
            }]
    )
    return message


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
        mimeType="text/plain",
    )

    return content


@pytest.fixture
def mock_embedded_resource():
    content = MagicMock()
    content.type = "embedded_resource"
    content.__class__.__name__ = "EmbeddedResource"
    content.resource = MagicMock()
    content.resource.model_dump_json.return_value = '{"resource_id": "123"}'
    return content


class TestMCPTool:
    
    @pytest.mark.asyncio
    async def test_builder_initialization(self):
        builder = MCPTool.Builder()
        assert isinstance(builder._tool, MCPTool)
        
    @pytest.mark.asyncio
    async def test_server_params_setting(self):
        builder = MCPTool.Builder()
        server_params = MagicMock()
        builder = builder.server_params(server_params)
        assert builder._tool.server_params == server_params
        
    @pytest.mark.asyncio
    async def test_build_function_specs(self, mock_stdio_client, mock_client_session, mock_tool_list):
        mock_client_session.list_tools.return_value = mock_tool_list
        
        builder = MCPTool.Builder()
        builder = builder.server_params(MagicMock())
        
        tool = await builder.build()
        
        assert len(tool.function_specs) == 1
        assert tool.function_specs[0].name == "test_tool"
        assert tool.function_specs[0].description == "Test tool description"
        
    @pytest.mark.asyncio
    async def test_a_execute_no_tool_calls(self):
        mcp_tool = MCPTool()
        context = ExecutionContext(
            conversation_id="test_conv",
            execution_id="test_execution_id",
            assistant_request_id="test_req",
        )
        message = Message(
            role="user",
            content="No tool calls here.",
        )
        
        with pytest.raises(ValueError, match="Function call is None."):
            async for _ in mcp_tool.a_execute(context, message):
                pass
                
    @pytest.mark.asyncio
    async def test_a_execute_text_content(self, mock_stdio_client, mock_client_session, 
                                         test_message, mock_text_content):
        # Setup
        mcp_tool = MCPTool()
        mcp_tool.function_specs = [FunctionSpec(name="test_function",
                    description="A test function",
                    parameters=ParametersSchema(
                        properties={
                            "arg1": ParameterSchema(
                                type="string", description="A test argument"
                            )
                        },
                        required=["arg1"],
                    ))]
        mcp_tool.server_params = MagicMock()
        context = ExecutionContext(
            conversation_id="test_conv",
            execution_id="test_execution_id",
            assistant_request_id="test_req",
        )
        
        # Mock call_tool response
        call_result = MagicMock()
        call_result.isError = False
        call_result.content = [mock_text_content]
        mock_client_session.call_tool.return_value = call_result
        
        # Execute and collect results
        results = []
        async for result in mcp_tool.a_execute(context, test_message):
            results.append(result)
        
        # Assertions
        assert len(results) == 1
        assert len(results[0]) == 1
        assert results[0][0].tool_call_id == "test_call_id"
        assert "Sample response text" in results[0][0].content
        
    @pytest.mark.asyncio
    async def test_a_execute_image_content(self, mock_stdio_client, mock_client_session, 
                                          test_message, mock_image_content):
        # Setup
        mcp_tool = MCPTool()
        mcp_tool.function_specs = [FunctionSpec(name="test_function",
                    description="A test function",
                    parameters=ParametersSchema(
                        properties={
                            "arg1": ParameterSchema(
                                type="string", description="A test argument"
                            )
                        },
                        required=["arg1"],
                    ))]
        mcp_tool.server_params = MagicMock()
        context = ExecutionContext(
            conversation_id="test_conv",
            execution_id="test_execution_id",
            assistant_request_id="test_req",
        )
        
        # Mock call_tool response
        call_result = MagicMock()
        call_result.isError = False
        call_result.content = [mock_image_content]
        mock_client_session.call_tool.return_value = call_result
        
        # Execute and collect results
        results = []
        async for result in mcp_tool.a_execute(context, test_message):
            results.append(result)
            
        # Verify the image data is returned
        assert len(results) == 1
        
    @pytest.mark.asyncio
    async def test_a_execute_error_response(self, mock_stdio_client, mock_client_session, test_message):
        # Setup
        mcp_tool = MCPTool()
        mcp_tool.function_specs = [FunctionSpec(name="test_function",
                    description="A test function",
                    parameters=ParametersSchema(
                        properties={
                            "arg1": ParameterSchema(
                                type="string", description="A test argument"
                            )
                        },
                        required=["arg1"],
                    ))]
        mcp_tool.server_params = MagicMock()
        context = ExecutionContext(
            conversation_id="test_conv",
            execution_id="test_execution_id",
            assistant_request_id="test_req",
        )
        
        # Mock error response
        call_result = MagicMock()
        call_result.isError = True
        call_result.content = "Error message"
        mock_client_session.call_tool.return_value = call_result
        
        # Execute and verify error is raised
        with pytest.raises(Exception, match="Error from MCP tool 'test_function'"):
            async for _ in mcp_tool.a_execute(context, test_message):
                pass