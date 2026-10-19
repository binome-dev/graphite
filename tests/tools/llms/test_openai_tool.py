import json
from typing import Any
from typing import List
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionChunk
from openai.types.chat import ChatCompletionMessage
from pydantic import BaseModel

from grafi.common.event_stores import EventStoreInMemory
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import Delta
from grafi.runtime import deltas_to
from grafi.tools.llms.impl.openai_adapter import to_openai_tool
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
        model="gpt-4.1-nano",
    )


def test_init(openai_instance):
    assert openai_instance.api_key == "test_api_key"
    assert openai_instance.model == "gpt-4.1-nano"
    assert openai_instance.system_message == "dummy system message"


@pytest.mark.asyncio
async def test_invoke_simple_response(monkeypatch, openai_instance, invoke_context):

    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(message=ChatCompletionMessage(role="assistant", content="Hello, world!"))
    ]

    # Create an async mock function that returns the mock response
    async def mock_create(*args, **kwargs):
        return mock_response

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    # Create async context manager mock
    async def mock_aenter(self):
        return mock_client

    async def mock_aexit(self, *args):
        pass

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = mock_aenter
    mock_context_manager.__aexit__ = mock_aexit

    # Mock the AsyncClient constructor to return our context manager
    mock_async_client_cls = MagicMock(return_value=mock_context_manager)
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient", mock_async_client_cls
    )

    input_data = [Message(role="user", content="Say hello")]
    result_messages = []
    async for message_batch in openai_instance.invoke(invoke_context, input_data):
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
async def test_invoke_function_call(monkeypatch, openai_instance, invoke_context):

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

    # Create async context manager mock
    async def mock_aenter(self):
        return mock_client

    async def mock_aexit(self, *args):
        pass

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = mock_aenter
    mock_context_manager.__aexit__ = mock_aexit

    # Mock the AsyncClient constructor to return our context manager
    mock_async_client_cls = MagicMock(return_value=mock_context_manager)
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient", mock_async_client_cls
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
    async for message_batch in openai_instance.invoke(invoke_context, input_data):
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
async def test_invoke_api_error(openai_instance, invoke_context):
    from grafi.common.exceptions import LLMToolException

    with pytest.raises(LLMToolException, match="Error code"):
        async for _ in openai_instance.invoke(
            invoke_context, [Message(role="user", content="Hello")]
        ):
            pass


def test_to_dict(openai_instance):
    result = openai_instance.to_dict()
    assert result["name"] == "OpenAITool"
    assert result["type"] == "OpenAITool"
    assert result["api_key"] == "****************"
    assert result["model"] == "gpt-4.1-nano"
    assert result["system_message"] == "dummy system message"
    assert result["oi_span_type"] == "LLM"


@pytest.mark.asyncio
async def test_from_dict():
    """Test deserialization from dictionary."""
    data = {
        "class": "OpenAITool",
        "tool_id": "test-id",
        "name": "TestOpenAI",
        "type": "OpenAITool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "gpt-4.1-nano",
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
        "structured_output": False,
    }

    tool = await OpenAITool.from_dict(data)

    assert isinstance(tool, OpenAITool)
    assert tool.name == "TestOpenAI"
    assert tool.model == "gpt-4.1-nano"
    assert tool.system_message == "You are helpful"
    assert tool.chat_params == {"temperature": 0.7}
    assert tool.is_streaming is False
    assert tool.structured_output is False


@pytest.mark.asyncio
async def test_from_dict_roundtrip(openai_instance):
    """Test that serialization and deserialization are consistent."""
    # Serialize to dict
    data = openai_instance.to_dict()

    # Deserialize back
    restored = await OpenAITool.from_dict(data)

    # Verify key properties match
    assert restored.name == openai_instance.name
    assert restored.model == openai_instance.model
    assert restored.system_message == openai_instance.system_message
    assert restored.chat_params == openai_instance.chat_params
    assert restored.is_streaming == openai_instance.is_streaming


# --------------------------------------------------------------------------- #
#  reasoning_effort / verbosity request params                                 #
# --------------------------------------------------------------------------- #
def test_extra_create_kwargs_set():
    tool = OpenAITool(api_key="k", reasoning_effort="high", verbosity="low")
    assert tool._extra_create_kwargs() == {
        "reasoning_effort": "high",
        "verbosity": "low",
    }


def test_extra_create_kwargs_empty_by_default():
    tool = OpenAITool(api_key="k")
    assert tool._extra_create_kwargs() == {}


@pytest.mark.asyncio
async def test_reasoning_verbosity_roundtrip():
    data = {
        "name": "TestOpenAI",
        "type": "OpenAITool",
        "oi_span_type": "LLM",
        "model": "gpt-5-mini",
        "reasoning_effort": "medium",
        "verbosity": "high",
    }
    tool = await OpenAITool.from_dict(data)
    assert tool.reasoning_effort == "medium"
    assert tool.verbosity == "high"
    assert tool.to_dict()["reasoning_effort"] == "medium"
    assert tool.to_dict()["verbosity"] == "high"


def test_prepare_api_input(openai_instance):
    input_data = [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="Hello!"),
        Message(role="assistant", content="Hi there! How can I help you today?"),
        Message(
            role="user",
            content="What's the weather like?",
            tools=[
                to_openai_tool(
                    FunctionSpec(
                        name="get_weather",
                        description="Get weather",
                        parameters=ParametersSchema(
                            type="object",
                            properties={"location": ParameterSchema(type="string")},
                        ),
                    )
                )
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


@pytest.mark.asyncio
async def test_client_close_failure_does_not_fail_completed_call(
    monkeypatch: pytest.MonkeyPatch,
    openai_instance: OpenAITool,
    invoke_context: InvokeContext,
) -> None:
    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(message=ChatCompletionMessage(role="assistant", content="done"))
    ]

    async def mock_create(*args: Any, **kwargs: Any) -> Mock:
        return mock_response

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    async def mock_aenter(self: Any) -> MagicMock:
        return mock_client

    async def mock_aexit(self: Any, *args: Any) -> None:
        raise OSError("connection pool shutdown failed")

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = mock_aenter
    mock_context_manager.__aexit__ = mock_aexit
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient",
        MagicMock(return_value=mock_context_manager),
    )

    result = [
        message
        async for batch in openai_instance.invoke(
            invoke_context, [Message(role="user", content="Hi")]
        )
        for message in batch
    ]
    assert [message.content for message in result] == ["done"]


class FakeStream:
    """An OpenAI response stream whose close fails."""

    def __init__(self, texts: List[str]) -> None:
        self.texts = texts
        self.exited = False

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        self.exited = True
        raise OSError("stream close failed")

    async def __aiter__(self) -> Any:
        for text in self.texts:
            yield ChatCompletionChunk.model_validate(
                {
                    "id": "c",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "m",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": text},
                            "finish_reason": None,
                        }
                    ],
                }
            )


@pytest.mark.asyncio
async def test_stream_is_closed_and_its_close_failure_does_not_fail_the_call(
    monkeypatch: pytest.MonkeyPatch,
    invoke_context: InvokeContext,
) -> None:
    stream = FakeStream(["a", "b"])

    async def mock_create(*args: Any, **kwargs: Any) -> FakeStream:
        return stream

    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    async def mock_aenter(self: Any) -> MagicMock:
        return mock_client

    async def mock_aexit(self: Any, *args: Any) -> None:
        return None

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = mock_aenter
    mock_context_manager.__aexit__ = mock_aexit
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient",
        MagicMock(return_value=mock_context_manager),
    )
    tool = OpenAITool(api_key="test_api_key")
    received: List[Delta] = []
    with deltas_to(received.append):
        result = [
            message.content
            async for batch in tool.invoke(
                invoke_context, [Message(role="user", content="Hi")]
            )
            for message in batch
        ]
    assert [delta.content for delta in received] == ["a", "b"]
    assert result == ["ab"]
    assert stream.exited


def _chunk(delta: dict, choices: bool = True) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": (
                [{"index": 0, "delta": delta, "finish_reason": None}] if choices else []
            ),
        }
    )


@pytest.mark.asyncio
async def test_a_streamed_answer_is_one_message_with_its_text_and_tool_calls(
    monkeypatch, openai_instance, invoke_context
):
    fragments = [
        {"role": "assistant", "content": "Checking."},
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "a",
                    "function": {"name": "weather", "arguments": ""},
                }
            ]
        },
        {
            "tool_calls": [
                {"index": 1, "id": "b", "function": {"name": "time", "arguments": ""}}
            ]
        },
        {"tool_calls": [{"index": 0, "function": {"arguments": '{"city": '}}]},
        {"tool_calls": [{"index": 1, "function": {"arguments": "{}"}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": '"Paris"}'}}]},
    ]

    class Stream:
        async def __aenter__(self) -> "Stream":
            return self

        async def __aexit__(self, *exc_info: Any) -> None:
            return None

        async def __aiter__(self) -> Any:
            for delta in fragments:
                yield _chunk(delta)
            yield _chunk({}, choices=False)  # A chunk of usage alone.

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=Stream())
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient",
        MagicMock(return_value=context),
    )
    received: List[Delta] = []
    with deltas_to(received.append):
        batches = [
            batch
            async for batch in openai_instance.invoke(
                invoke_context, [Message(role="user", content="Weather and time?")]
            )
        ]

    [[message]] = batches
    assert [delta.content for delta in received] == ["Checking."]
    assert message.content == "Checking."
    assert [call.model_dump() for call in message.tool_calls] == [
        {
            "id": "a",
            "type": "function",
            "function": {"name": "weather", "arguments": '{"city": "Paris"}'},
        },
        {
            "id": "b",
            "type": "function",
            "function": {"name": "time", "arguments": "{}"},
        },
    ]  # Their standard fields only.


@pytest.mark.asyncio
async def test_with_is_streaming_off_the_provider_is_not_streamed(
    monkeypatch, openai_instance, invoke_context
):
    create = AsyncMock(
        return_value=ChatCompletion.model_validate(
            {
                "id": "c",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "whole"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )
    )
    client = MagicMock()
    client.chat.completions.create = create
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient",
        MagicMock(return_value=context),
    )
    openai_instance.is_streaming = False  # Off: whole, though the caller streams.
    with deltas_to(lambda delta: None):
        [[message]] = [
            batch
            async for batch in openai_instance.invoke(
                invoke_context, [Message(role="user", content="Hi")]
            )
        ]
    assert message.content == "whole"
    assert "stream" not in create.call_args.kwargs


@pytest.mark.asyncio
async def test_fields_a_provider_repeats_in_every_chunk_are_not_joined(
    monkeypatch, openai_instance, invoke_context
):
    call = {"index": 0, "id": "a", "function": {"name": "weather"}}
    fragments = [
        {"role": "assistant", "content": "Check"},
        {"role": "assistant", "content": "ing."},
        {
            "role": "assistant",
            "tool_calls": [
                {**call, "function": {"name": "weather", "arguments": '{"city": '}}
            ],
        },
        {
            "role": "assistant",
            "tool_calls": [
                {**call, "function": {"name": "weather", "arguments": '"Paris"}'}}
            ],
        },
    ]

    class Stream:
        async def __aenter__(self) -> "Stream":
            return self

        async def __aexit__(self, *exc_info: Any) -> None:
            return None

        async def __aiter__(self) -> Any:
            for delta in fragments:
                yield _chunk(delta)

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=Stream())
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient",
        MagicMock(return_value=context),
    )
    with deltas_to(lambda delta: None):
        [[message]] = [
            batch
            async for batch in openai_instance.invoke(
                invoke_context, [Message(role="user", content="Weather?")]
            )
        ]
    assert (message.role, message.content) == ("assistant", "Checking.")
    [tool_call] = message.tool_calls
    assert (tool_call.id, tool_call.function.name) == ("a", "weather")
    assert tool_call.function.arguments == '{"city": "Paris"}'


def _streaming_client(monkeypatch: pytest.MonkeyPatch, chunks: List[Any]) -> MagicMock:
    """A patched client whose create() streams ``chunks``."""

    class Stream:
        async def __aenter__(self) -> "Stream":
            return self

        async def __aexit__(self, *exc_info: Any) -> None:
            return None

        async def __aiter__(self) -> Any:
            for chunk in chunks:
                yield chunk

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=Stream())
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient",
        MagicMock(return_value=context),
    )
    return client


async def _streamed_answer(tool: OpenAITool, context: InvokeContext) -> Message:
    with deltas_to(lambda delta: None):
        [[message]] = [
            batch
            async for batch in tool.invoke(context, [Message(role="user", content="?")])
        ]
    return message


@pytest.mark.asyncio
async def test_whole_calls_sent_at_one_index_stay_apart(
    monkeypatch, openai_instance, invoke_context
):
    def whole(call_id: str, city: str) -> ChatCompletionChunk:
        arguments = json.dumps({"city": city})
        return _chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": call_id,
                        "function": {"name": "weather", "arguments": arguments},
                    }
                ]
            }
        )

    _streaming_client(monkeypatch, [whole("a", "Paris"), whole("b", "Tokyo")])
    message = await _streamed_answer(openai_instance, invoke_context)
    assert [(c.id, c.function.arguments) for c in message.tool_calls] == [
        ("a", '{"city": "Paris"}'),
        ("b", '{"city": "Tokyo"}'),
    ]


@pytest.mark.asyncio
async def test_a_streamed_answer_keeps_its_annotations_and_its_first_choice(
    monkeypatch, openai_instance, invoke_context
):
    citation = {
        "type": "url_citation",
        "url_citation": {
            "url": "https://example.com",
            "title": "Example",
            "start_index": 0,
            "end_index": 4,
        },
    }
    other_choice = ChatCompletionChunk.model_validate(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [
                {"index": 1, "delta": {"content": "other"}, "finish_reason": None}
            ],
        }
    )
    a_file = {"type": "file", "file": {"hash": "h", "name": "doc.pdf"}}
    client = _streaming_client(
        monkeypatch,
        [
            _chunk({"role": "assistant", "content": "Here"}),
            other_choice,
            _chunk({"annotations": [citation, a_file]}),  # As OpenRouter adds.
        ],
    )
    message = await _streamed_answer(openai_instance, invoke_context)
    assert message.content == "Here"
    [annotation] = message.annotations  # The citation: a message holds those.
    assert annotation.url_citation.url == "https://example.com"
    stream_options = client.chat.completions.create.call_args.kwargs["stream_options"]
    assert stream_options == {"include_usage": True}


@pytest.mark.asyncio
async def test_structured_output_is_parsed_whole_though_the_caller_streams(
    monkeypatch, invoke_context
):
    class Answer(BaseModel):
        city: str

    client = MagicMock()
    client.beta.chat.completions.parse = AsyncMock(
        return_value=ChatCompletion.model_validate(
            {
                "id": "c",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"city":"Oslo"}'},
                        "finish_reason": "stop",
                    }
                ],
            }
        )
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient",
        MagicMock(return_value=context),
    )
    tool = (
        OpenAITool.builder()
        .api_key("k")
        .chat_params({"response_format": Answer})
        .build()
    )
    message = await _streamed_answer(tool, invoke_context)
    assert message.content == '{"city":"Oslo"}'
    client.chat.completions.create.assert_not_called()
