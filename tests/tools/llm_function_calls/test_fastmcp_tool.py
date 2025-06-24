from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import pytest_asyncio
from openai.types.chat.chat_completion_message import FunctionCall

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.fastmcp_tool import FastMCPTool


@pytest_asyncio.fixture
def client_config():
    return {"mcpServers": ["http://localhost:1234"]}


@pytest_asyncio.fixture
def tool_builder(client_config):
    return FastMCPTool.builder().client_config(client_config)


@pytest.mark.asyncio
@patch("grafi.tools.function_calls.impl.fastmcp_tool.Client")
async def test_a_get_function_specs_loads_tools(mock_client_cls, tool_builder):
    mock_client = AsyncMock()
    mock_tool = MagicMock()
    mock_tool.name = "test_tool"
    mock_tool.description = "desc"
    mock_tool.inputSchema = {"type": "object"}
    mock_client.list_tools = AsyncMock(return_value=[mock_tool])
    mock_client.list_resources = AsyncMock(return_value=[])
    mock_client.list_prompts = AsyncMock(return_value=[])
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    tool = tool_builder._obj
    await tool._a_get_function_specs()
    assert tool.function_specs[0].name == "test_tool"
    assert tool.prompts == []
    assert tool.resources == []


@pytest.mark.asyncio
@patch("grafi.tools.function_calls.impl.fastmcp_tool.Client")
async def test_a_invoke_success(mock_client_cls, tool_builder):
    mock_client = AsyncMock()
    mock_client.is_connected.return_value = True
    # Simulate TextContent result
    text_content = MagicMock()
    text_content.text = "result"
    text_content.__class__.__name__ = "TextContent"
    mock_client.call_tool = AsyncMock(return_value=[text_content])
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    tool = tool_builder._obj
    tool.function_specs = [MagicMock(name="test_tool")]
    tool.client_config = {"mcpServers": ["http://localhost:1234"]}

    # Construct a valid tool_call and Message
    tool_call = {
        "id": "callid",
        "function": FunctionCall(name="test_tool", arguments='{"arg": 1}').model_dump(),
        "type": "function",
    }
    msg = Message(role="user", content="", tool_calls=[tool_call])
    input_data = [msg]
    invoke_context = InvokeContext(
        conversation_id="test_conversation",
        invoke_id="test_invoke",
        assistant_request_id="test_request_id",
    )

    gen = tool.a_invoke(invoke_context, input_data)
    messages = await anext(gen)
    assert messages
    assert any("result" in (m.content or "") for m in messages)


@pytest.mark.asyncio
@patch("grafi.tools.function_calls.impl.fastmcp_tool.Client")
async def test_a_invoke_raises_on_missing_tool_calls(mock_client_cls, tool_builder):
    tool = tool_builder._obj
    tool.function_specs = []
    tool.client_config = {"mcpServers": ["http://localhost:1234"]}
    # Message must have required fields
    msg = Message(role="user", content="", tool_calls=None)
    input_data = [msg]
    invoke_context = InvokeContext(
        conversation_id="test_conversation",
        invoke_id="test_invoke",
        assistant_request_id="test_request_id",
    )
    with pytest.raises(ValueError):
        gen = tool.a_invoke(invoke_context, input_data)
        await anext(gen)


@pytest.mark.asyncio
@patch("grafi.tools.function_calls.impl.fastmcp_tool.Client")
async def test_a_invoke_raises_on_missing_client_config(mock_client_cls, tool_builder):
    tool = tool_builder._obj
    tool.function_specs = [MagicMock(name="test_tool")]
    tool.client_config = None
    tool_call = {
        "id": "callid",
        "function": FunctionCall(name="test_tool", arguments='{"arg": 1}').model_dump(),
        "type": "function",
    }
    msg = Message(role="user", content="", tool_calls=[tool_call])
    input_data = [msg]
    invoke_context = InvokeContext(
        conversation_id="test_conversation",
        invoke_id="test_invoke",
        assistant_request_id="test_request_id",
    )
    with pytest.raises(ValueError):
        gen = tool.a_invoke(invoke_context, input_data)
        await anext(gen)
