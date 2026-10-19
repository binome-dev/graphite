from typing import Any
from typing import AsyncIterator
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
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
    client = MagicMock()
    client.close = AsyncMock()

    async def aexit(self: Any, *exc_info: Any) -> None:
        await client.close()  # As ollama.AsyncClient.__aexit__ does.

    client.__aexit__ = aexit
    mock = Mock(return_value=client)
    monkeypatch.setattr("ollama.AsyncClient", mock)
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


@pytest.mark.asyncio
async def test_invoke(monkeypatch, invoke_context, mock_ollama_client):
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

    # Make the chat method return a coroutine that resolves to the mock_response
    async def mock_chat(*args, **kwargs):
        return mock_response

    mock_ollama_client.return_value.chat = mock_chat
    result = []
    async for msg in tool.invoke(invoke_context, input_data):
        result.extend(msg)

    assert result[0].role == "assistant"
    assert result[0].content == "Hi there!"
    mock_ollama_client.assert_called_once_with("http://localhost:11434")


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


@pytest.mark.asyncio
async def test_from_dict():
    """Test deserialization from dictionary."""
    data = {
        "class": "OllamaTool",
        "tool_id": "test-id",
        "name": "TestOllama",
        "type": "OllamaTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "qwen3",
        "api_url": "http://localhost:11434",
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
        "structured_output": False,
    }

    tool = await OllamaTool.from_dict(data)

    assert isinstance(tool, OllamaTool)
    assert tool.name == "TestOllama"
    assert tool.model == "qwen3"
    assert tool.api_url == "http://localhost:11434"
    assert tool.system_message == "You are helpful"


@pytest.mark.asyncio
async def test_from_dict_roundtrip():
    """Test that serialization and deserialization are consistent."""
    original = OllamaTool(
        system_message="Test system",
        name="TestOllama",
        model="qwen3",
        api_url="http://localhost:11434",
    )

    # Serialize to dict
    data = original.to_dict()

    # Deserialize back
    restored = await OllamaTool.from_dict(data)

    # Verify key properties match
    assert restored.name == original.name
    assert restored.model == original.model
    assert restored.api_url == original.api_url
    assert restored.system_message == original.system_message


def test_prepare_api_input_forwards_tool_calls():
    """Assistant tool_calls must be forwarded to Ollama (not silently dropped)."""
    from openai.types.chat.chat_completion_message_tool_call import (
        ChatCompletionMessageToolCall,
    )
    from openai.types.chat.chat_completion_message_tool_call import Function

    tool = OllamaTool(name="OllamaTool", model="qwen3", api_url="http://localhost")
    tool_call = ChatCompletionMessageToolCall(
        id="call_1",
        type="function",
        function=Function(name="get_weather", arguments='{"location": "Paris"}'),
    )
    msgs = [Message(role="assistant", content="", tool_calls=[tool_call])]

    api_messages, _ = tool.prepare_api_input(msgs)

    assistant_msg = api_messages[-1]
    assert "tool_calls" in assistant_msg
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "get_weather"
    assert assistant_msg["tool_calls"][0]["function"]["arguments"] == {
        "location": "Paris"
    }


@pytest.mark.asyncio
async def test_early_close_releases_stream_and_client(
    invoke_context: InvokeContext, mock_ollama_client: Mock
) -> None:
    closed: list[str] = []

    async def chunks() -> AsyncIterator[ChatResponse]:
        try:
            for text in ("a", "b"):
                yield ChatResponse.model_validate(
                    {"message": {"role": "assistant", "content": text}}
                )
        finally:
            closed.append("stream")

    async def mock_chat(*args: Any, **kwargs: Any) -> AsyncIterator[ChatResponse]:
        return chunks()

    mock_ollama_client.return_value.chat = mock_chat
    tool = OllamaTool(is_streaming=True)
    stream = tool.invoke(invoke_context, [Message(role="user", content="Hi")])
    await anext(stream)
    await stream.aclose()
    assert closed == ["stream"]
    mock_ollama_client.return_value.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_close_failure_on_early_close_is_not_a_call_failure(
    invoke_context: InvokeContext, mock_ollama_client: Mock
) -> None:
    async def chunks() -> AsyncIterator[ChatResponse]:
        try:
            for text in ("a", "b"):
                yield ChatResponse.model_validate(
                    {"message": {"role": "assistant", "content": text}}
                )
        finally:
            raise OSError("stream close failed")

    async def mock_chat(*args: Any, **kwargs: Any) -> AsyncIterator[ChatResponse]:
        return chunks()

    mock_ollama_client.return_value.chat = mock_chat
    tool = OllamaTool(is_streaming=True)
    stream = tool.invoke(invoke_context, [Message(role="user", content="Hi")])
    await anext(stream)
    await stream.aclose()  # Releasing the stream failed; the call did not.
    mock_ollama_client.return_value.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_client_close_failure_does_not_fail_completed_call(
    invoke_context: InvokeContext, mock_ollama_client: Mock
) -> None:
    async def mock_chat(*args: Any, **kwargs: Any) -> ChatResponse:
        return ChatResponse.model_validate(
            {"message": {"role": "assistant", "content": "done"}}
        )

    mock_ollama_client.return_value.chat = mock_chat
    mock_ollama_client.return_value.close = AsyncMock(side_effect=OSError("close"))
    tool = OllamaTool()
    result = [
        message
        async for batch in tool.invoke(
            invoke_context, [Message(role="user", content="Hi")]
        )
        for message in batch
    ]
    assert [message.content for message in result] == ["done"]
