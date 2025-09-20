from typing import List
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
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


@pytest.mark.asyncio
async def test_a_invoke_simple_response(monkeypatch, openai_instance, invoke_context):
    import grafi.tools.llms.impl.openai_tool

    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(message=ChatCompletionMessage(role="assistant", content="Hello, world!"))
    ]

    # Create an async mock function that returns the mock response
    async def mock_create(*args, **kwargs):
        return mock_response

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    # Mock the AsyncClient constructor
    mock_async_client_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr(
        grafi.tools.llms.impl.openai_tool, "AsyncClient", mock_async_client_cls
    )

    input_data = [Message(role="user", content="Say hello")]
    result_messages = []
    async for message_batch in openai_instance.a_invoke(invoke_context, input_data):
        result_messages.extend(message_batch)

    assert isinstance(result_messages, List)
    assert result_messages[0].role == "assistant"
    assert result_messages[0].content == "Hello, world!"

    # Verify client was initialized with the right API key
    mock_async_client_cls.assert_called_once_with(api_key="test_api_key")

    # Note: We can't easily verify the async mock call parameters
    # The important verification is that the client was initialized correctly
    # and the response processing works


@pytest.mark.asyncio
async def test_a_invoke_function_call(monkeypatch, openai_instance, invoke_context):
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

    # Create an async mock function that returns the mock response
    async def mock_create(*args, **kwargs):
        return mock_response

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    # Mock the AsyncClient constructor
    mock_async_client_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr(
        grafi.tools.llms.impl.openai_tool, "AsyncClient", mock_async_client_cls
    )

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
    result_messages = []
    async for message_batch in openai_instance.a_invoke(invoke_context, input_data):
        result_messages.extend(message_batch)

    assert isinstance(result_messages, List)
    assert result_messages[0].role == "assistant"
    assert result_messages[0].content is None
    assert isinstance(result_messages[0].tool_calls, list)
    assert result_messages[0].tool_calls[0].id == "test_id"
    assert (
        result_messages[0].tool_calls[0].function.arguments == '{"location": "London"}'
    )
    # Note: We can't easily verify the async mock call parameters
    # The important verification is that the tool calls were processed correctly


@pytest.mark.asyncio
async def test_a_invoke_api_error(openai_instance, invoke_context):
    from grafi.common.exceptions import LLMToolException

    with pytest.raises(LLMToolException, match="Error code"):
        async for _ in openai_instance.a_invoke(
            invoke_context, [Message(role="user", content="Hello")]
        ):
            pass


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
