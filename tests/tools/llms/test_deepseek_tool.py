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
from grafi.tools.llms.impl.deepseek_tool import DeepseekTool


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

    import grafi.tools.llms.impl.deepseek_tool

    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(message=ChatCompletionMessage(role="assistant", content="Hello, world!"))
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    # Patch the OpenAI.Client constructor the tool uses
    mock_openai_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr(
        grafi.tools.llms.impl.deepseek_tool, "AsyncClient", mock_openai_cls
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
        api_key="test_api_key", base_url="https://api.deepseek.com"
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
    assert call_args["tools"] is None


# --------------------------------------------------------------------------- #
#  invoke() – function call path
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_function_call(monkeypatch, deepseek_instance, invoke_context):
    from unittest.mock import AsyncMock

    import grafi.tools.llms.impl.deepseek_tool

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
    monkeypatch.setattr(
        grafi.tools.llms.impl.deepseek_tool,
        "AsyncClient",
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
    import grafi.tools.llms.impl.deepseek_tool

    # Force constructor to raise – simulates any client error
    def _raise(*_a, **_kw):  # noqa: D401
        raise Exception("Error code")

    monkeypatch.setattr(grafi.tools.llms.impl.deepseek_tool, "AsyncClient", _raise)

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
#  to_dict()                                                                   #
# --------------------------------------------------------------------------- #
def test_to_dict(deepseek_instance):
    result = deepseek_instance.to_dict()
    assert result["name"] == "DeepseekTool"
    assert result["type"] == "DeepseekTool"
    assert result["api_key"] == "****************"
    assert result["model"] == "deepseek-chat"
    assert result["base_url"] == "https://api.deepseek.com"


# --------------------------------------------------------------------------- #
#  from_dict()                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_from_dict():
    """Test deserialization from dictionary."""
    data = {
        "class": "DeepseekTool",
        "tool_id": "test-id",
        "name": "TestDeepseek",
        "type": "DeepseekTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
        "structured_output": False,
    }

    tool = await DeepseekTool.from_dict(data)

    assert isinstance(tool, DeepseekTool)
    assert tool.name == "TestDeepseek"
    assert tool.model == "deepseek-chat"
    assert tool.base_url == "https://api.deepseek.com"
    assert tool.system_message == "You are helpful"
    assert tool.chat_params == {"temperature": 0.7}


@pytest.mark.asyncio
async def test_from_dict_roundtrip(deepseek_instance):
    """Test that serialization and deserialization are consistent."""
    # Serialize to dict
    data = deepseek_instance.to_dict()

    # Deserialize back
    restored = await DeepseekTool.from_dict(data)

    # Verify key properties match
    assert restored.name == deepseek_instance.name
    assert restored.model == deepseek_instance.model
    assert restored.base_url == deepseek_instance.base_url
    assert restored.system_message == deepseek_instance.system_message
