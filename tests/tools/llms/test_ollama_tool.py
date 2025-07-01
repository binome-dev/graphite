from unittest.mock import Mock

import pytest
from ollama import ChatResponse

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.llms.impl.ollama_tool import OllamaTool


@pytest.fixture
def invoke_context():
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id="invoke_id",
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
    assert tool.model == "qwen3"


def test_prepare_api_input():
    tool = OllamaTool(system_message="System message")
    input_data = [
        Message(role="user", content="Hello"),
        Message(role="assistant", content="Hi there!"),
        Message(
            role="user",
            content="Can you call this function?",
        ),
    ]
    tool.add_function_specs(
        [
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
    )
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


def test_invoke(monkeypatch, invoke_context, mock_ollama_client):
    tool = OllamaTool()
    input_data = [Message(role="user", content="Hello")]

    mock_response = ChatResponse.model_validate(
        {
            "message": {
                "role": "assistant",
                "content": "Hi there!",
            }
        }
    )
    mock_ollama_client.return_value.chat.return_value = mock_response

    result = tool.invoke(invoke_context, input_data)

    assert result[0].role == "assistant"
    assert result[0].content == "Hi there!"
    mock_ollama_client.assert_called_once_with("http://localhost:11434")
    mock_ollama_client.return_value.chat.assert_called_once_with(
        model="qwen3", messages=[{"role": "user", "content": "Hello"}], tools=None
    )


def test_to_messages():
    tool = OllamaTool()
    response = ChatResponse.model_validate(
        {
            "message": {
                "role": "assistant",
                "content": "Hi there!",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "test_function",
                            "arguments": {"arg1": "value1"},
                        },
                    }
                ],
            }
        }
    )
    message = tool.to_messages(response)

    assert message[0].role == "assistant"
    assert message[0].content == "Hi there!"
    assert len(message[0].tool_calls) == 1
    assert message[0].tool_calls[0].function.name == "test_function"
    assert message[0].tool_calls[0].function.arguments == '{"arg1": "value1"}'
