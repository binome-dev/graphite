from typing import List
from unittest.mock import ANY
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from openai import omit
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionMessage
from pydantic_core import PydanticSerializationError

from grafi.common.event_stores import EventStoreInMemory
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.llms.impl.deepseek_tool import DeepseekTool
from grafi.tools.tool import Tool


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #
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
def deepseek_instance():
    return DeepseekTool(
        system_message="dummy system message",
        name="DeepseekTool",
        api_key="test_api_key",
        model="deepseek-chat",
    )


# --------------------------------------------------------------------------- #
#  Basic initialisation
# --------------------------------------------------------------------------- #
def test_init(deepseek_instance):
    assert deepseek_instance.api_key == "test_api_key"
    assert deepseek_instance.model == "deepseek-chat"
    assert deepseek_instance.system_message == "dummy system message"


# --------------------------------------------------------------------------- #
#  invoke() – simple assistant response
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_simple_response(monkeypatch, deepseek_instance, invoke_context):
    from unittest.mock import AsyncMock

    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(message=ChatCompletionMessage(role="assistant", content="Hello, world!"))
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    # Patch the OpenAI.Client constructor the tool uses
    mock_openai_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr(
        "grafi.tools.llms.impl.openai_compatible.AsyncClient", mock_openai_cls
    )

    input_data = [Message(role="user", content="Say hello")]
    result_messages = []
    async for message_batch in deepseek_instance.invoke(invoke_context, input_data):
        result_messages.extend(message_batch)

    assert isinstance(result_messages, List)
    assert result_messages[0].role == "assistant"
    assert result_messages[0].content == "Hello, world!"

    # Constructor must receive both api_key and base_url
    mock_openai_cls.assert_called_once_with(
        api_key="test_api_key", base_url="https://api.deepseek.com", default_headers=ANY
    )

    # Verify parameters passed to completions.create
    mock_client.chat.completions.create.assert_called_once()
    call_args = mock_client.chat.completions.create.call_args[1]
    assert call_args["model"] == "deepseek-chat"
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
    assert call_args["tools"] is omit


# --------------------------------------------------------------------------- #
#  invoke() – function call path
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_function_call(monkeypatch, deepseek_instance, invoke_context):
    from unittest.mock import AsyncMock

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

    # user msg + attached function spec
    input_data = [Message(role="user", content="What's the weather in London?")]
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
    deepseek_instance.add_function_specs(tools)

    result_messages = []
    async for message_batch in deepseek_instance.invoke(invoke_context, input_data):
        result_messages.extend(message_batch)

    assert result_messages[0].role == "assistant"
    assert result_messages[0].content is None
    assert isinstance(result_messages[0].tool_calls, list)
    assert result_messages[0].tool_calls[0].id == "test_id"

    call_args = mock_client.chat.completions.create.call_args[1]
    assert call_args["model"] == "deepseek-chat"
    assert call_args["tools"] == [
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


# --------------------------------------------------------------------------- #
#  Error handling
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_api_error(monkeypatch, deepseek_instance, invoke_context):

    # Force constructor to raise – simulates any client error
    def _raise(*_a, **_kw):  # noqa: D401
        raise Exception("Error code")

    monkeypatch.setattr("grafi.tools.llms.impl.openai_compatible.AsyncClient", _raise)

    from grafi.common.exceptions import LLMToolException

    with pytest.raises(LLMToolException, match="Error code"):
        async for _ in deepseek_instance.invoke(
            invoke_context, [Message(role="user", content="Hi")]
        ):
            pass


# --------------------------------------------------------------------------- #
#  prepare_api_input() helper
# --------------------------------------------------------------------------- #
def test_prepare_api_input(deepseek_instance):
    input_data = [
        Message(role="system", content="You are helpful."),
        Message(role="user", content="Hello!"),
        Message(role="assistant", content="Hi there!"),
        Message(
            role="user",
            content="Weather in London?",
        ),
    ]

    deepseek_instance.add_function_specs(
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
    api_messages, api_functions = deepseek_instance.prepare_api_input(input_data)

    assert api_messages == [
        {"role": "system", "content": "dummy system message"},
        {
            "name": None,
            "role": "system",
            "content": "You are helpful.",
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
            "content": "Hi there!",
            "tool_calls": None,
            "tool_call_id": None,
        },
        {
            "name": None,
            "role": "user",
            "content": "Weather in London?",
            "tool_calls": None,
            "tool_call_id": None,
        },
    ]

    assert list(api_functions) == [
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


# --------------------------------------------------------------------------- #
#  Saving and loading                                                          #
# --------------------------------------------------------------------------- #
DEEPSEEK_TOOL = "grafi.tools.llms.impl.deepseek_tool:DeepseekTool"


@pytest.fixture
def saved_deepseek(monkeypatch: pytest.MonkeyPatch) -> DeepseekTool:
    """A DeepseekTool with every field set, its key from DEEPSEEK_API_KEY."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test_api_key")
    return DeepseekTool(
        name="TestDeepseek",
        system_message="You are helpful",
        api_key="test_api_key",
        model="deepseek-reasoner",
        base_url="https://deepseek.example/v1",
        chat_params={"temperature": 0.7},
        is_streaming=False,
    )


def test_dump_names_the_class_and_saves_the_key_as_its_variable(saved_deepseek):
    assert saved_deepseek.model_dump(mode="json") == {
        "class": DEEPSEEK_TOOL,
        "tool_id": saved_deepseek.tool_id,
        "name": "TestDeepseek",
        "type": "DeepseekTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "api_key": {"env": "DEEPSEEK_API_KEY"},
        "model": "deepseek-reasoner",
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
        "structured_output": False,
        "base_url": "https://deepseek.example/v1",
    }


def test_round_trip(saved_deepseek):
    data = saved_deepseek.model_dump(mode="json")

    restored = Tool.model_validate(data)

    assert type(restored) is DeepseekTool
    assert restored.tool_id == saved_deepseek.tool_id
    assert restored.api_key == "test_api_key"  # Read from DEEPSEEK_API_KEY.
    assert restored.base_url == "https://deepseek.example/v1"
    assert restored == saved_deepseek
    assert restored.model_dump(mode="json") == data


def test_load_from_a_manifest_naming_the_class():
    data = {
        "class": DEEPSEEK_TOOL,
        "tool_id": "test-id",
        "name": "TestDeepseek",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "deepseek-chat",
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
    }

    tool = Tool.model_validate(data)

    assert isinstance(tool, DeepseekTool)
    assert tool.tool_id == "test-id"
    assert tool.name == "TestDeepseek"
    assert tool.model == "deepseek-chat"
    assert tool.base_url == "https://api.deepseek.com"  # The default.
    assert tool.system_message == "You are helpful"
    assert tool.chat_params == {"temperature": 0.7}


def test_a_key_not_from_its_variable_is_never_saved(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "the_env_key")
    tool = DeepseekTool(api_key="another_key")

    with pytest.raises(
        PydanticSerializationError, match="ManifestError: .*DeepseekTool.api_key"
    ):
        tool.model_dump(mode="json")
