from typing import List
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionMessage

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.llms.impl.openrouter_tool import OpenRouterTool


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
def test_invoke_simple_response(monkeypatch, openrouter_instance, invoke_context):
    import grafi.tools.llms.impl.openrouter_tool as or_module

    # Fake successful response
    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(message=ChatCompletionMessage(role="assistant", content="Hello, world!"))
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = MagicMock(return_value=mock_response)

    # Patch the OpenAI class used inside the tool
    monkeypatch.setattr(or_module, "OpenAI", MagicMock(return_value=mock_client))

    result = openrouter_instance.invoke(
        invoke_context, [Message(role="user", content="Say hello")]
    )

    # Assertions on result
    assert isinstance(result, List)
    assert result[0].role == "assistant"
    assert result[0].content == "Hello, world!"

    # OpenAI ctor must receive correct kwargs
    or_module.OpenAI.assert_called_once_with(
        api_key="test_api_key", base_url="https://openrouter.ai/api/v1"
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
def test_invoke_with_extra_headers(monkeypatch, openrouter_instance, invoke_context):
    import grafi.tools.llms.impl.openrouter_tool as or_module

    openrouter_instance.extra_headers = {
        "HTTP-Referer": "https://my-app.example",
        "X-Title": "UnitTest",
    }

    mock_response = Mock(spec=ChatCompletion)
    mock_response.choices = [
        Mock(message=ChatCompletionMessage(role="assistant", content="Hi!"))
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = MagicMock(return_value=mock_response)
    monkeypatch.setattr(or_module, "OpenAI", MagicMock(return_value=mock_client))

    openrouter_instance.invoke(
        invoke_context, [Message(role="user", content="Hi there")]
    )

    # ensure headers propagated
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["extra_headers"] == openrouter_instance.extra_headers


# --------------------------------------------------------------------------- #
#  Function / tool-call path
# --------------------------------------------------------------------------- #
def test_invoke_function_call(monkeypatch, openrouter_instance, invoke_context):
    import grafi.tools.llms.impl.openrouter_tool as or_module

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
    monkeypatch.setattr(or_module, "OpenAI", MagicMock(return_value=mock_client))

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
    result = openrouter_instance.invoke(invoke_context, input_data)

    assert result[0].tool_calls[0].id == "test_id"
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["tools"] is not None


# --------------------------------------------------------------------------- #
#  Error propagation
# --------------------------------------------------------------------------- #
def test_invoke_api_error(monkeypatch, openrouter_instance, invoke_context):
    import grafi.tools.llms.impl.openrouter_tool as or_module

    def _raise(*_a, **_kw):  # pragma: no cover
        raise Exception("Error code")

    monkeypatch.setattr(or_module, "OpenAI", _raise)

    with pytest.raises(RuntimeError, match="OpenRouter API error: Error code"):
        openrouter_instance.invoke(invoke_context, [Message(role="user", content="Hi")])


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
    assert api_tools is None
    assert api_messages[0]["content"] == "dummy system message"
    assert api_messages[-1]["role"] == "assistant"
    assert api_messages[-1]["content"] == "Hi there."


# --------------------------------------------------------------------------- #
#  to_dict
# --------------------------------------------------------------------------- #
def test_to_dict(openrouter_instance):
    d = openrouter_instance.to_dict()
    assert d["name"] == "OpenRouterTool"
    assert d["type"] == "OpenRouterTool"
    assert d["api_key"] == "****************"
    assert d["model"] == "openrouter/auto"
    assert d["base_url"] == "https://openrouter.ai/api/v1"
