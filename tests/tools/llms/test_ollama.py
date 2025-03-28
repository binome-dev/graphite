from unittest.mock import Mock

import pytest

from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import (
    FunctionSpec,
    ParameterSchema,
    ParametersSchema,
)
from grafi.common.models.message import Message
from grafi.tools.llms.impl.ollama_tool import OllamaTool


@pytest.fixture
def execution_context():
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id="execution_id",
        assistant_request_id="assistant_request_id",
    )


@pytest.fixture
def mock_ollama_client(monkeypatch):
    mock = Mock()
    monkeypatch.setattr("ollama.Client", mock)
    return mock


def test_ollama_tool_initialization():
    tool = OllamaTool()
    assert tool.name == "OllamaTool"
    assert tool.type == "OllamaTool"
    assert tool.api_url == "http://localhost:11434"
    assert tool.model == "qwen2.5"


def test_prepare_api_input():
    tool = OllamaTool(system_message="System message")
    input_data = [
        Message(role="user", content="Hello"),
        Message(role="assistant", content="Hi there!"),
        Message(
            role="user",
            content="Can you call this function?",
            tools=[
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
                ).to_openai_tool()
            ],
        ),
    ]
    api_messages, api_functions = tool.prepare_api_input(input_data)

    assert api_messages == [
        {"role": "system", "content": "System message"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "Can you call this function?"},
    ]
    api_functions_obj = list(api_functions)
    assert api_functions_obj[0] == {
        "function": {
            "description": "A test function",
            "name": "test_function",
            "parameters": {
                "properties": {
                    "arg1": {"description": "A test argument", "type": "string"}
                },
                "required": ["arg1"],
                "type": "object",
            },
        },
        "type": "function",
    }


def test_execute(monkeypatch, execution_context, mock_ollama_client):
    tool = OllamaTool()
    input_data = [Message(role="user", content="Hello")]

    mock_response = {
        "message": {
            "role": "assistant",
            "content": "Hi there!",
        }
    }
    mock_ollama_client.return_value.chat.return_value = mock_response

    result = tool.execute(execution_context, input_data)

    assert result.role == "assistant"
    assert result.content == "Hi there!"
    mock_ollama_client.assert_called_once_with("http://localhost:11434")
    mock_ollama_client.return_value.chat.assert_called_once_with(
        model="qwen2.5", messages=[{"role": "user", "content": "Hello"}], tools=[]
    )


def test_to_message():
    tool = OllamaTool()
    response = {
        "message": {
            "role": "assistant",
            "content": "Hi there!",
            "tool_calls": [
                {
                    "id": "test_id",
                    "type": "function",
                    "function": {
                        "name": "test_function",
                        "arguments": {"arg1": "value1"},
                    },
                }
            ],
        }
    }
    message = tool.to_message(response)

    assert message.role == "assistant"
    assert message.content == "Hi there!"
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].id == "test_id"
    assert message.tool_calls[0].function.name == "test_function"
    assert message.tool_calls[0].function.arguments == '{"arg1": "value1"}'
