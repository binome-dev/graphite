from typing import List
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from openai import NOT_GIVEN
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionMessage

from grafi.common.event_stores import EventStoreInMemory
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.llms.impl.openai_tool import OpenAITool


@pytest.fixture
def event_store():
    return EventStoreInMemory()


@pytest.fixture
def invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id="invoke_id",
        assistant_request_id="assistant_request_id",
    )


@pytest.fixture
def openai_instance():
    return OpenAITool(
        system_message="dummy system message",
        name="OpenAITool",
        api_key="test_api_key",
        model="gpt-4o-mini",
    )


def test_init(openai_instance):
    assert openai_instance.api_key == "test_api_key"
    assert openai_instance.model == "gpt-4o-mini"
    assert openai_instance.system_message == "dummy system message"


def test_invoke_simple_response(monkeypatch, openai_instance, invoke_context):
    import grafi.tools.llms.impl.openai_tool

    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(message=ChatCompletionMessage(role="assistant", content="Hello, world!"))
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = MagicMock(return_value=mock_response)

    # Mock the OpenAI client constructor
    mock_openai_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr(grafi.tools.llms.impl.openai_tool, "OpenAI", mock_openai_cls)

    input_data = [Message(role="user", content="Say hello")]
    result = openai_instance.invoke(invoke_context, input_data)

    assert isinstance(result, List)
    assert result[0].role == "assistant"
    assert result[0].content == "Hello, world!"

    # Verify client was initialized with the right API key
    mock_openai_cls.assert_called_once_with(api_key="test_api_key")

    # Verify create was called with right parameters
    mock_client.chat.completions.create.assert_called_once()
    call_args = mock_client.chat.completions.create.call_args[1]
    assert call_args["model"] == "gpt-4o-mini"
    assert call_args["messages"] == [
        {"role": "system", "content": "dummy system message"},
        {
            "name": None,
            "role": "user",
            "content": "Say hello",
            "tool_calls": None,
            "tool_call_id": None,
        },
    ]
    assert call_args["tools"] is NOT_GIVEN


def test_invoke_function_call(monkeypatch, openai_instance, invoke_context):
    import grafi.tools.llms.impl.openai_tool

    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(
            message=ChatCompletionMessage(
                role="assistant",
                content=None,
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
        )
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = MagicMock(return_value=mock_response)

    # Mock the OpenAI client constructor
    mock_openai_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr(grafi.tools.llms.impl.openai_tool, "OpenAI", mock_openai_cls)

    input_data = [Message(role="user", content="What's the weather in London?")]
    tools = [
        FunctionSpec(
            name="get_weather",
            description="Get weather",
            parameters=ParametersSchema(
                type="object", properties={"location": ParameterSchema(type="string")}
            ),
        )
    ]
    openai_instance.add_function_specs(tools)
    result = openai_instance.invoke(invoke_context, input_data)

    assert isinstance(result, List)
    assert result[0].role == "assistant"
    assert result[0].content is None
    assert isinstance(result[0].tool_calls, list)
    assert result[0].tool_calls[0].id == "test_id"
    assert result[0].tool_calls[0].function.arguments == '{"location": "London"}'
    mock_client.chat.completions.create.assert_called_once()
    call_args = mock_client.chat.completions.create.call_args[1]
    assert call_args["model"] == "gpt-4o-mini"
    assert call_args["messages"] == [
        {"role": "system", "content": "dummy system message"},
        {
            "role": "user",
            "name": None,
            "tool_calls": None,
            "tool_call_id": None,
            "content": "What's the weather in London?",
        },
    ]
    assert call_args["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string", "description": ""}},
                    "required": [],
                },
            },
        }
    ]


def test_invoke_api_error(openai_instance, invoke_context):
    with pytest.raises(RuntimeError, match="OpenAI API error: Error code"):
        openai_instance.invoke(invoke_context, [Message(role="user", content="Hello")])


def test_to_dict(openai_instance):
    result = openai_instance.to_dict()
    assert result["name"] == "OpenAITool"
    assert result["type"] == "OpenAITool"
    assert result["api_key"] == "****************"
    assert result["model"] == "gpt-4o-mini"
    assert result["system_message"] == "dummy system message"
    assert result["oi_span_type"] == "LLM"


def test_prepare_api_input(openai_instance):
    input_data = [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="Hello!"),
        Message(role="assistant", content="Hi there! How can I help you today?"),
        Message(
            role="user",
            content="What's the weather like?",
            tools=[
                FunctionSpec(
                    name="get_weather",
                    description="Get weather",
                    parameters=ParametersSchema(
                        type="object",
                        properties={"location": ParameterSchema(type="string")},
                    ),
                ).to_openai_tool()
            ],
        ),
    ]
    openai_instance.add_function_specs(
        [
            FunctionSpec(
                name="get_weather",
                description="Get weather",
                parameters=ParametersSchema(
                    type="object",
                    properties={"location": ParameterSchema(type="string")},
                ),
            )
        ]
    )
    api_messages, api_functions = openai_instance.prepare_api_input(input_data)

    assert api_messages == [
        {"role": "system", "content": "dummy system message"},
        {
            "name": None,
            "role": "system",
            "content": "You are a helpful assistant.",
            "tool_calls": None,
            "tool_call_id": None,
        },
        {
            "name": None,
            "role": "user",
            "content": "Hello!",
            "tool_calls": None,
            "tool_call_id": None,
        },
        {
            "name": None,
            "role": "assistant",
            "content": "Hi there! How can I help you today?",
            "tool_calls": None,
            "tool_call_id": None,
        },
        {
            "name": None,
            "role": "user",
            "content": "What's the weather like?",
            "tool_calls": None,
            "tool_call_id": None,
        },
    ]

    api_functions_obj = list(api_functions)

    assert api_functions_obj == [
        {
            "function": {
                "description": "Get weather",
                "name": "get_weather",
                "parameters": {
                    "properties": {"location": {"description": "", "type": "string"}},
                    "required": [],
                    "type": "object",
                },
            },
            "type": "function",
        }
    ]
