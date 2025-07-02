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
def test_invoke_simple_response(monkeypatch, deepseek_instance, invoke_context):
    import grafi.tools.llms.impl.deepseek_tool as dst_module

    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(message=ChatCompletionMessage(role="assistant", content="Hello, world!"))
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = MagicMock(return_value=mock_response)

    # Patch the OpenAI.Client constructor the tool uses
    mock_openai_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr(dst_module, "OpenAI", mock_openai_cls)

    input_data = [Message(role="user", content="Say hello")]
    result = deepseek_instance.invoke(invoke_context, input_data)

    assert isinstance(result, List)
    assert result[0].role == "assistant"
    assert result[0].content == "Hello, world!"

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
def test_invoke_function_call(monkeypatch, deepseek_instance, invoke_context):
    import grafi.tools.llms.impl.deepseek_tool as dst_module

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
    monkeypatch.setattr(dst_module, "OpenAI", MagicMock(return_value=mock_client))

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

    result = deepseek_instance.invoke(invoke_context, input_data)

    assert result[0].role == "assistant"
    assert result[0].content is None
    assert isinstance(result[0].tool_calls, list)
    assert result[0].tool_calls[0].id == "test_id"

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
def test_invoke_api_error(monkeypatch, deepseek_instance, invoke_context):
    import grafi.tools.llms.impl.deepseek_tool as dst_module

    # Force constructor to raise – simulates any client error
    def _raise(*_a, **_kw):  # noqa: D401
        raise Exception("Error code")

    monkeypatch.setattr(dst_module, "OpenAI", _raise)

    with pytest.raises(RuntimeError, match="DeepSeek API error: Error code"):
        deepseek_instance.invoke(invoke_context, [Message(role="user", content="Hi")])


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
