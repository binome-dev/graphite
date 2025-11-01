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
from grafi.tools.llms.impl.qwen_tool import QwenTool


@pytest.fixture
def event_store():
    """Create an in-memory event store for testing."""
    return EventStoreInMemory()


@pytest.fixture
def invoke_context() -> InvokeContext:
    """Create a test invoke context with sample IDs."""
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id="invoke_id",
        assistant_request_id="assistant_request_id",
    )


@pytest.fixture
def qwen_instance():
    """Create a QwenTool instance with test configuration."""
    return QwenTool(
        system_message="dummy system message",
        name="QwenTool",
        api_key="test_api_key",
        model="qwen-plus",
    )


def test_init(qwen_instance):
    """Test that QwenTool initializes with correct attributes."""
    assert qwen_instance.api_key == "test_api_key"
    assert qwen_instance.model == "qwen-plus"
    assert qwen_instance.system_message == "dummy system message"
    assert qwen_instance.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


@pytest.mark.asyncio
async def test_invoke_simple_response(monkeypatch, qwen_instance, invoke_context):
    """Test simple text response from Qwen API."""
    import grafi.tools.llms.impl.qwen_tool

    # Create a mock response object
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
        grafi.tools.llms.impl.qwen_tool, "AsyncClient", mock_async_client_cls
    )

    input_data = [Message(role="user", content="Say hello")]
    result_messages = []
    async for message_batch in qwen_instance.invoke(invoke_context, input_data):
        result_messages.extend(message_batch)

    assert isinstance(result_messages, List)
    assert result_messages[0].role == "assistant"
    assert result_messages[0].content == "Hello, world!"

    # Verify client was initialized with the right API key and base URL
    mock_async_client_cls.assert_called_once_with(
        api_key="test_api_key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


@pytest.mark.asyncio
async def test_invoke_function_call(monkeypatch, qwen_instance, invoke_context):
    """Test function call response from Qwen API."""
    import grafi.tools.llms.impl.qwen_tool

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
        grafi.tools.llms.impl.qwen_tool, "AsyncClient", mock_async_client_cls
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
    qwen_instance.add_function_specs(tools)
    result_messages = []
    async for message_batch in qwen_instance.invoke(invoke_context, input_data):
        result_messages.extend(message_batch)

    assert isinstance(result_messages, List)
    assert result_messages[0].role == "assistant"
    assert result_messages[0].content is None
    assert isinstance(result_messages[0].tool_calls, list)
    assert result_messages[0].tool_calls[0].id == "test_id"
    assert (
        result_messages[0].tool_calls[0].function.arguments == '{"location": "London"}'
    )


@pytest.mark.asyncio
async def test_invoke_api_error(qwen_instance, invoke_context):
    """Test that API errors are properly handled and converted to LLMToolException."""
    from grafi.common.exceptions import LLMToolException

    with pytest.raises(LLMToolException, match="Error code|Qwen API"):
        async for _ in qwen_instance.invoke(
            invoke_context, [Message(role="user", content="Hello")]
        ):
            pass


def test_to_dict(qwen_instance):
    """Test conversion of QwenTool instance to dictionary format."""
    result = qwen_instance.to_dict()
    assert result["name"] == "QwenTool"
    assert result["type"] == "QwenTool"
    assert result["api_key"] == "****************"
    assert result["model"] == "qwen-plus"
    assert result["system_message"] == "dummy system message"
    assert result["oi_span_type"] == "LLM"
    assert result["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_prepare_api_input(qwen_instance):
    """Test preparation of input data for Qwen API format."""
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
    qwen_instance.add_function_specs(
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
    api_messages, api_functions = qwen_instance.prepare_api_input(input_data)

    # Verify the system message is prepended
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

    # Verify the function specifications are correctly formatted
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

