import uuid
from unittest.mock import Mock

import pytest

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.agent_calling_tool import AgentCallingTool


@pytest.fixture
def mock_agent_call():
    return Mock(return_value={"content": "mocked response"})


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


def test_invoke_successful(agent_calling_tool):
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

    result = agent_calling_tool.invoke(invoke_context, input_data)
    print(result)

    assert result[0].role == "tool"
    assert result[0].content == "mocked response"
    assert result[0].tool_call_id == "test_id"


def test_invoke_invalid_function_name(agent_calling_tool):
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

    result = agent_calling_tool.invoke(invoke_context, input_data)

    assert result[0].content is None


def test_invoke_none_function_call(agent_calling_tool):
    invoke_context = InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )
    input_data = [Message(role="assistant")]

    with pytest.raises(ValueError, match="Agent call is None."):
        agent_calling_tool.invoke(invoke_context, input_data)


def test_to_messages(agent_calling_tool):
    response = "test response"
    result = agent_calling_tool.to_messages(response, "test_id")

    assert result[0].role == "tool"
    assert result[0].content == "test response"
    assert result[0].tool_call_id == "test_id"


def test_to_dict(agent_calling_tool: AgentCallingTool):
    result = agent_calling_tool.to_dict()
    assert isinstance(result, dict)
    assert result["name"] == "test_agent"
    assert result["agent_description"] == "Test agent description"
