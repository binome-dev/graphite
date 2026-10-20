import uuid
from unittest.mock import Mock

import pytest
from pydantic_core import PydanticSerializationError

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.agent_calling_tool import AgentCallingTool
from grafi.tools.tool import Tool


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


AGENT_CALLING_TOOL = (
    "grafi.tools.function_calls.impl.agent_calling_tool:AgentCallingTool"
)


def test_dump(serializable_agent_tool: AgentCallingTool):
    result = serializable_agent_tool.model_dump(mode="json")
    assert result["class"] == AGENT_CALLING_TOOL
    assert result["name"] == "test_agent"
    assert result["agent_name"] == "test_agent"
    assert result["agent_description"] == "Test agent description"
    assert result["argument_description"] == "Test argument description"
    # agent_call serializes as an import reference, no pickle blob.
    assert result["agent_call"] == {"ref": f"{__name__}:sample_agent_call"}
    # Its spec follows from its fields, so it is not saved.
    assert "function_specs" not in result
    assert result["functions"] == {}


def test_load_from_a_manifest_naming_the_class():
    """Test loading from a dictionary with an agent_call reference."""
    data = {
        "class": AGENT_CALLING_TOOL,
        "tool_id": "test-id",
        "name": "test_agent",
        "oi_span_type": "TOOL",
        "agent_name": "test_agent",
        "agent_description": "Test description",
        "argument_description": "Test args",
        "agent_call": {"ref": f"{__name__}:sample_agent_call"},
    }

    tool = Tool.model_validate(data)

    assert isinstance(tool, AgentCallingTool)
    assert tool.tool_id == "test-id"
    assert tool.name == "test_agent"
    assert tool.agent_name == "test_agent"
    assert tool.agent_description == "Test description"
    assert tool.argument_description == "Test args"
    assert tool.agent_call is sample_agent_call
    # The agent's spec is made from its fields.
    [spec] = tool.function_specs
    assert spec.name == "test_agent"
    assert spec.description == "Test description"


@pytest.mark.asyncio
async def test_round_trip(serializable_agent_tool, invoke_context):
    data = serializable_agent_tool.model_dump(mode="json")

    restored = Tool.model_validate(data)

    assert type(restored) is AgentCallingTool
    assert restored.tool_id == serializable_agent_tool.tool_id
    assert restored.agent_call is sample_agent_call
    assert restored.function_specs == serializable_agent_tool.function_specs
    assert restored == serializable_agent_tool
    assert restored.model_dump(mode="json") == data
    calls = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "a",
                "type": "function",
                "function": {"name": "test_agent", "arguments": '{"prompt": "hi"}'},
            }
        ],
    )
    [[answer]] = [batch async for batch in restored.invoke(invoke_context, [calls])]
    assert answer.content == "sample response"


def test_an_agent_call_that_cannot_be_referenced_is_not_saved(agent_calling_tool):
    # A mock, like a lambda or a nested function, has no import path.
    with pytest.raises(PydanticSerializationError, match="Cannot serialize callable"):
        agent_calling_tool.model_dump(mode="json")


def test_renaming_the_agent_in_a_dump_offers_only_the_new_name(
    serializable_agent_tool,
):
    data = serializable_agent_tool.model_dump(mode="json")
    data["agent_name"] = "renamed_agent"
    data["agent_description"] = "An edited description."

    restored = Tool.model_validate(data)

    [spec] = restored.function_specs
    assert spec.name == "renamed_agent"
    assert spec.description == "An edited description."
    assert list(spec.parameters.properties) == ["prompt"]


def test_saving_and_loading_again_does_not_grow_the_specs(serializable_agent_tool):
    tool = serializable_agent_tool

    for _ in range(3):
        tool = Tool.model_validate(tool.model_dump(mode="json"))
        tool = AgentCallingTool.model_validate(tool.model_dump())

    assert tool.function_specs == serializable_agent_tool.function_specs
    assert [spec.name for spec in tool.function_specs] == ["test_agent"]
