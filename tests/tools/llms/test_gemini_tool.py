from typing import List
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.llms.impl.gemini_tool import GeminiTool


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conv_id",
        invoke_id="exec_id",
        assistant_request_id="req_id",
    )


@pytest.fixture
def gemini_instance() -> GeminiTool:
    return GeminiTool(
        system_message="dummy system message",
        name="GeminiTool",
        api_key="test_api_key",
        model="gemini-2.0-flash-lite",
    )


# --------------------------------------------------------------------------- #
#  Basic initialisation
# --------------------------------------------------------------------------- #
def test_init(gemini_instance):
    assert gemini_instance.api_key == "test_api_key"
    assert gemini_instance.model == "gemini-2.0-flash-lite"
    assert gemini_instance.system_message == "dummy system message"


# --------------------------------------------------------------------------- #
#  invoke() — simple reply
# --------------------------------------------------------------------------- #
def test_invoke_simple_response(monkeypatch, gemini_instance, invoke_context):
    import grafi.tools.llms.impl.gemini_tool as gm_module

    # Fake GenerateContentResponse object – only `.text` is accessed
    mock_response = Mock()
    mock_response.text = "Hello, world!"
    mock_response.function_calls = None

    # Stub client and method
    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)

    # Patch genai.Client ctor inside the module
    monkeypatch.setattr(
        gm_module, "genai", MagicMock(Client=MagicMock(return_value=mock_client))
    )

    input_data = [Message(role="user", content="Say hello")]
    result = gemini_instance.invoke(invoke_context, input_data)

    assert isinstance(result, List)
    assert result[0].role == "assistant"
    assert result[0].content == "Hello, world!"

    # Ensure generate_content called with correct args
    mock_client.models.generate_content.assert_called_once()
    call_kwargs = mock_client.models.generate_content.call_args[1]
    assert call_kwargs["model"] == "gemini-2.0-flash-lite"

    # Contents must include system message
    assert call_kwargs["contents"][0].role == "user"
    assert call_kwargs["contents"][0].parts[0].text == "dummy system message"


# --------------------------------------------------------------------------- #
#  invoke() — tool / function call path
# --------------------------------------------------------------------------- #
def test_invoke_function_call(monkeypatch, gemini_instance, invoke_context):
    import grafi.tools.llms.impl.gemini_tool as gm_module

    # TODO: improve this unit tests
    # Gemini returns text inline even for tool calls; we'll just check param passing
    mock_response = Mock()
    mock_response.text = ""  # empty because function call chosen
    mock_function_call = Mock()
    mock_function_call.id = "function_call_id"
    mock_function_call.name = "get_weather"
    mock_function_call.args = {
        "location": "London",
        "unit": "Celsius",
        "time": "now",
    }
    mock_response.function_calls = [mock_function_call]

    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)
    monkeypatch.setattr(
        gm_module, "genai", MagicMock(Client=MagicMock(return_value=mock_client))
    )

    # prepare input message with a tool definition
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

    gemini_instance.add_function_specs(tools)

    gemini_instance.invoke(invoke_context, input_data)

    call_kwargs = mock_client.models.generate_content.call_args[1]
    # The GenerateContentConfig should contain our tool schema
    assert call_kwargs is not None


# --------------------------------------------------------------------------- #
#  Error propagation
# --------------------------------------------------------------------------- #
def test_invoke_api_error(monkeypatch, gemini_instance, invoke_context):
    import grafi.tools.llms.impl.gemini_tool as gm_module

    def _raise(*_a, **_kw):  # pragma: no cover
        raise Exception("Failure")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = _raise
    monkeypatch.setattr(
        gm_module, "genai", MagicMock(Client=MagicMock(return_value=mock_client))
    )

    with pytest.raises(RuntimeError, match="Gemini API error: Failure"):
        gemini_instance.invoke(invoke_context, [Message(role="user", content="Hi")])


# --------------------------------------------------------------------------- #
#  prepare_api_input helper
# --------------------------------------------------------------------------- #
def test_prepare_api_input(gemini_instance):
    msgs = [
        Message(role="system", content="You are helpful."),
        Message(role="user", content="Hello!"),
        Message(role="assistant", content="Hi there."),
    ]

    contents, tools = gemini_instance.prepare_api_input(msgs)

    assert contents[0].role == "user"  # dummy system msg added later
    assert contents[-1].role == "model"
    assert tools == [] or tools is None


# --------------------------------------------------------------------------- #
#  to_dict()                                                                   #
# --------------------------------------------------------------------------- #
def test_to_dict(gemini_instance):
    d = gemini_instance.to_dict()
    assert d["name"] == "GeminiTool"
    assert d["type"] == "GeminiTool"
    assert d["api_key"] == "****************"
    assert d["model"] == "gemini-2.0-flash-lite"
