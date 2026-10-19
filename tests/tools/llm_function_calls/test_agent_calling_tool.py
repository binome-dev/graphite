import uuid
from unittest.mock import Mock

import pytest

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.agent_calling_tool import AgentCallingTool


async def sample_agent_call(*args, **kwargs):
    """Module-level agent call -> serializes as an import reference (no pickle)."""
    return {"content": "sample response"}


@pytest.fixture
def mock_agent_call():
    async def async_mock_agent_call(*args, **kwargs):
        return {"content": "mocked response"}

    return Mock(side_effect=async_mock_agent_call)


@pytest.fixture
def serializable_agent_tool() -> AgentCallingTool:
    """An AgentCallingTool whose agent_call is a referenceable module function."""
    return (
        AgentCallingTool.builder()
        .agent_name("test_agent")
        .agent_description("Test agent description")
        .argument_description("Test argument description")
        .agent_call(sample_agent_call)
        .build()
    )


@pytest.fixture
def agent_calling_tool(mock_agent_call) -> AgentCallingTool:
    return (
        AgentCallingTool.builder()
        .agent_name("test_agent")
        .agent_description("Test agent description")
        .argument_description("Test argument description")
        .agent_call(mock_agent_call)
        .build()
    )


def test_agent_calling_tool_initialization(agent_calling_tool):
    assert agent_calling_tool.name == "test_agent"
    assert agent_calling_tool.type == "AgentCallingTool"
    assert agent_calling_tool.agent_name == "test_agent"
    assert agent_calling_tool.agent_description == "Test agent description"
    assert agent_calling_tool.argument_description == "Test argument description"


def test_get_function_specs(agent_calling_tool):
    specs = agent_calling_tool.get_function_specs()
    assert len(specs) == 1
    assert specs[0].name == "test_agent"
    assert specs[0].description == "Test agent description"
    assert specs[0].parameters.type == "object"
    assert "prompt" in specs[0].parameters.properties
    assert specs[0].parameters.required == ["prompt"]


@pytest.mark.asyncio
async def test_invoke_successful(agent_calling_tool):
    invoke_context = InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )
    input_data = [
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "test_id",
                    "type": "function",
                    "function": {
                        "name": "test_agent",
                        "arguments": '{"prompt": "test prompt"}',
                    },
                }
            ],
        )
    ]
    result = []
    async for msg in agent_calling_tool.invoke(invoke_context, input_data):
        result.extend(msg)

    assert result[0].role == "tool"
    assert result[0].content == "mocked response"
    assert result[0].tool_call_id == "test_id"


@pytest.mark.asyncio
async def test_invoke_invalid_function_name(agent_calling_tool):
    invoke_context = InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )
    input_data = [
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "test_id",
                    "type": "function",
                    "function": {
                        "name": "wrong_agent",
                        "arguments": '{"prompt": "test prompt"}',
                    },
                }
            ],
        )
    ]

    [answer] = [
        message
        async for messages in agent_calling_tool.invoke(invoke_context, input_data)
        for message in messages
    ]
    assert answer.content.startswith("Error: LookupError: No function 'wrong_agent'")


@pytest.mark.asyncio
async def test_invoke_none_function_call(agent_calling_tool):
    invoke_context = InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )
    input_data = [Message(role="assistant")]

    outputs = [m async for m in agent_calling_tool.invoke(invoke_context, input_data)]
    assert outputs == []  # No tool call, no result.


def test_to_dict(serializable_agent_tool: AgentCallingTool):
    result = serializable_agent_tool.to_dict()
    assert isinstance(result, dict)
    assert result["name"] == "test_agent"
    assert result["agent_description"] == "Test agent description"
    # agent_call serializes as an import reference, no pickle blob.
    assert result["agent_call"] == {"ref": f"{__name__}:sample_agent_call"}


@pytest.mark.asyncio
async def test_from_dict():
    """Test deserialization from a dictionary with an agent_call reference."""
    data = {
        "class": "AgentCallingTool",
        "tool_id": "test-id",
        "name": "test_agent",
        "type": "AgentCallingTool",
        "oi_span_type": "TOOL",
        "agent_name": "test_agent",
        "agent_description": "Test description",
        "argument_description": "Test args",
        "agent_call": {"ref": f"{__name__}:sample_agent_call"},
    }

    tool = await AgentCallingTool.from_dict(data)

    assert isinstance(tool, AgentCallingTool)
    assert tool.name == "test_agent"
    assert tool.agent_name == "test_agent"
    assert tool.agent_description == "Test description"
    assert tool.argument_description == "Test args"
    assert tool.agent_call is sample_agent_call


@pytest.mark.asyncio
async def test_from_dict_roundtrip(serializable_agent_tool):
    """Test that serialization and deserialization are consistent."""
    # Serialize to dict
    data = serializable_agent_tool.to_dict()

    # Deserialize back
    restored = await AgentCallingTool.from_dict(data)

    # Verify key properties match
    assert restored.name == serializable_agent_tool.name
    assert restored.agent_name == serializable_agent_tool.agent_name
    assert restored.agent_description == serializable_agent_tool.agent_description
    assert restored.argument_description == serializable_agent_tool.argument_description
    assert restored.agent_call is sample_agent_call
