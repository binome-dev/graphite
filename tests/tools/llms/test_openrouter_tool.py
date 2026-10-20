from typing import List
from unittest.mock import ANY
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from openai import omit
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionMessage
from pydantic_core import PydanticSerializationError

from grafi.common.manifest import ManifestError
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.llms.impl.openrouter_tool import OpenRouterTool
from grafi.tools.tool import Tool


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id="invoke_id",
        assistant_request_id="assistant_request_id",
    )


@pytest.fixture
def openrouter_instance():
    return OpenRouterTool(
        system_message="dummy system message",
        name="OpenRouterTool",
        api_key="test_api_key",
        model="openrouter/auto",
    )


# --------------------------------------------------------------------------- #
#  Basic initialisation
# --------------------------------------------------------------------------- #
def test_init(openrouter_instance):
    assert openrouter_instance.api_key == "test_api_key"
    assert openrouter_instance.model == "openrouter/auto"
    assert openrouter_instance.system_message == "dummy system message"
    assert openrouter_instance.base_url == "https://openrouter.ai/api/v1"
    assert openrouter_instance.extra_headers == {}


# --------------------------------------------------------------------------- #
#  Simple assistant reply
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_simple_response(monkeypatch, openrouter_instance, invoke_context):
    # Fake successful response
    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(message=ChatCompletionMessage(role="assistant", content="Hello, world!"))
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    # Patch the OpenAI class used inside the shared base tool
    mock_async_client_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient", mock_async_client_cls
    )

    result_messages = []
    async for message_batch in openrouter_instance.invoke(
        invoke_context, [Message(role="user", content="Say hello")]
    ):
        result_messages.extend(message_batch)

    # Assertions on result
    assert isinstance(result_messages, List)
    assert result_messages[0].role == "assistant"
    assert result_messages[0].content == "Hello, world!"

    # AsyncClient ctor must receive correct kwargs
    mock_async_client_cls.assert_called_once_with(
        api_key="test_api_key",
        base_url="https://openrouter.ai/api/v1",
        default_headers=ANY,
    )

    # Verify parameters forwarded to completions.create
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "openrouter/auto"
    assert call_kwargs["extra_headers"] is None
    assert call_kwargs["messages"][0]["role"] == "system"
    assert call_kwargs["messages"][0]["content"] == "dummy system message"


# --------------------------------------------------------------------------- #
#  With extra headers
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_with_extra_headers(
    monkeypatch, openrouter_instance, invoke_context
):

    openrouter_instance.extra_headers = {
        "HTTP-Referer": "https://my-app.example",
        "X-Title": "UnitTest",
    }

    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(message=ChatCompletionMessage(role="assistant", content="Hi!"))
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient",
        MagicMock(return_value=mock_client),
    )

    result_messages = []
    async for message_batch in openrouter_instance.invoke(
        invoke_context, [Message(role="user", content="Hi there")]
    ):
        result_messages.extend(message_batch)

    # ensure headers propagated
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["extra_headers"] == openrouter_instance.extra_headers


# --------------------------------------------------------------------------- #
#  Function / tool-call path
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_function_call(monkeypatch, openrouter_instance, invoke_context):

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
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient",
        MagicMock(return_value=mock_client),
    )

    tools = [
        FunctionSpec(
            name="get_weather",
            description="Get weather",
            parameters=ParametersSchema(
                type="object",
                properties={"location": ParameterSchema(type="string")},
            ),
        )
    ]

    input_data = [Message(role="user", content="Weather?")]
    openrouter_instance.add_function_specs(tools)
    result_messages = []
    async for message_batch in openrouter_instance.invoke(invoke_context, input_data):
        result_messages.extend(message_batch)

    assert result_messages[0].tool_calls[0].id == "test_id"
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["tools"] is not None


# --------------------------------------------------------------------------- #
#  Error propagation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_api_error(monkeypatch, openrouter_instance, invoke_context):

    def _raise(*_a, **_kw):  # pragma: no cover
        raise Exception("Error code")

    monkeypatch.setattr("grafi.tools.llms.impl.openai_compatible.AsyncClient", _raise)

    from grafi.common.exceptions import LLMToolException

    with pytest.raises(LLMToolException, match="Error code"):
        async for _ in openrouter_instance.invoke(
            invoke_context, [Message(role="user", content="Hi")]
        ):
            pass


# --------------------------------------------------------------------------- #
#  prepare_api_input helper
# --------------------------------------------------------------------------- #
def test_prepare_api_input(openrouter_instance):
    input_data = [
        Message(role="system", content="You are helpful."),
        Message(role="user", content="Hello!"),
        Message(role="assistant", content="Hi there."),
    ]

    api_messages, api_tools = openrouter_instance.prepare_api_input(input_data)
    assert api_tools is omit
    assert api_messages[0]["content"] == "dummy system message"
    assert api_messages[-1]["role"] == "assistant"
    assert api_messages[-1]["content"] == "Hi there."


# --------------------------------------------------------------------------- #
#  Saving and loading
# --------------------------------------------------------------------------- #
OPENROUTER_TOOL = "grafi.tools.llms.impl.openrouter_tool:OpenRouterTool"


@pytest.fixture
def saved_openrouter(monkeypatch: pytest.MonkeyPatch) -> OpenRouterTool:
    """An OpenRouterTool with every field set, its key from OPENROUTER_API_KEY."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test_api_key")
    return OpenRouterTool(
        name="TestOpenRouter",
        system_message="You are helpful",
        api_key="test_api_key",
        model="anthropic/claude-haiku-4-5",
        base_url="https://openrouter.example/api/v1",
        extra_headers={"HTTP-Referer": "https://example.com", "X-Title": "Test"},
        chat_params={"temperature": 0.7},
        is_streaming=False,
    )


def test_dump_names_the_class_and_saves_the_key_as_its_variable(saved_openrouter):
    assert saved_openrouter.model_dump(mode="json") == {
        "class": OPENROUTER_TOOL,
        "tool_id": saved_openrouter.tool_id,
        "name": "TestOpenRouter",
        "type": "OpenRouterTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "api_key": {"env": "OPENROUTER_API_KEY"},
        "model": "anthropic/claude-haiku-4-5",
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
        "structured_output": False,
        "base_url": "https://openrouter.example/api/v1",
        "extra_headers": {"HTTP-Referer": "https://example.com", "X-Title": "Test"},
    }


def test_round_trip(saved_openrouter):
    data = saved_openrouter.model_dump(mode="json")

    restored = Tool.model_validate(data)

    assert type(restored) is OpenRouterTool
    assert restored.tool_id == saved_openrouter.tool_id
    assert restored.api_key == "test_api_key"  # Read from OPENROUTER_API_KEY.
    assert restored.base_url == "https://openrouter.example/api/v1"
    assert restored.extra_headers == {
        "HTTP-Referer": "https://example.com",
        "X-Title": "Test",
    }
    assert restored == saved_openrouter
    assert restored.model_dump(mode="json") == data


def test_load_from_a_manifest_naming_the_class():
    data = {
        "class": OPENROUTER_TOOL,
        "tool_id": "test-id",
        "name": "TestOpenRouter",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "openrouter/auto",
        "extra_headers": {"X-Title": "Test"},
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
    }

    tool = Tool.model_validate(data)

    assert isinstance(tool, OpenRouterTool)
    assert tool.tool_id == "test-id"
    assert tool.name == "TestOpenRouter"
    assert tool.model == "openrouter/auto"
    assert tool.base_url == "https://openrouter.ai/api/v1"  # The default.
    assert tool.extra_headers == {"X-Title": "Test"}
    assert tool.system_message == "You are helpful"


def test_a_key_not_from_its_variable_is_never_saved(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "the_env_key")
    tool = OpenRouterTool(api_key="another_key")

    with pytest.raises(
        PydanticSerializationError, match="ManifestError: .*OpenRouterTool.api_key"
    ):
        tool.model_dump(mode="json")


@pytest.mark.parametrize("header", ["Authorization", "X-Api-Key", "Cookie"])
def test_a_secret_header_set_to_a_value_is_never_saved(header):
    tool = OpenRouterTool(extra_headers={"X-Title": "Test", header: "literal"})

    with pytest.raises(
        PydanticSerializationError,
        match=f"ManifestError: .*OpenRouterTool.extra_headers holds a secret, at "
        f"'{header}'",
    ):
        tool.model_dump(mode="json")
    with pytest.raises(ManifestError, match=f"holds a secret, at '{header}'"):
        tool.to_manifest()
    # A python-mode dump holds values.
    assert tool.model_dump()["extra_headers"][header] == "literal"
