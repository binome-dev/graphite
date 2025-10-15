from typing import List
from unittest.mock import AsyncMock
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
@pytest.mark.asyncio
async def test_invoke_simple_response(monkeypatch, gemini_instance, invoke_context):
    import grafi.tools.llms.impl.gemini_tool as gm_module

    # Fake GenerateContentResponse object – only `.text` is accessed
    mock_response = Mock()
    mock_response.text = "Hello, world!"
    mock_response.function_calls = None

    # Stub client and method - need to mock the async aio interface
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    # Patch genai.Client ctor inside the module
    monkeypatch.setattr(
        gm_module, "genai", MagicMock(Client=MagicMock(return_value=mock_client))
    )

    input_data = [Message(role="user", content="Say hello")]
    result = []
    async for msg in gemini_instance.invoke(invoke_context, input_data):
        result.extend(msg)

    assert isinstance(result, List)
    assert result[0].role == "assistant"
    assert result[0].content == "Hello, world!"

    # Ensure generate_content called with correct args
    mock_client.aio.models.generate_content.assert_called_once()
    call_kwargs = mock_client.aio.models.generate_content.call_args[1]
    assert call_kwargs["model"] == "gemini-2.0-flash-lite"

    # Contents must include system message
    assert call_kwargs["contents"][0].role == "user"
    assert call_kwargs["contents"][0].parts[0].text == "dummy system message"


# --------------------------------------------------------------------------- #
#  invoke() — tool / function call path
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_function_call(monkeypatch, gemini_instance, invoke_context):
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
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
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

    async for msg in gemini_instance.invoke(invoke_context, input_data):
        assert msg

    call_kwargs = mock_client.aio.models.generate_content.call_args[1]
    # The GenerateContentConfig should contain our tool schema
    assert call_kwargs is not None


# --------------------------------------------------------------------------- #
#  Error propagation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_api_error(monkeypatch, gemini_instance, invoke_context):
    import grafi.tools.llms.impl.gemini_tool as gm_module

    def _raise(*_a, **_kw):  # pragma: no cover
        raise Exception("Failure")

    mock_client = MagicMock()
    mock_client.aio.models.generate_content.side_effect = _raise
    monkeypatch.setattr(
        gm_module, "genai", MagicMock(Client=MagicMock(return_value=mock_client))
    )

    from grafi.common.exceptions import LLMToolException

    with pytest.raises(LLMToolException, match="Failure"):
        async for _ in gemini_instance.invoke(
            invoke_context, [Message(role="user", content="Hi")]
        ):
            pass  # Exception should be raised before we get any results


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


# --------------------------------------------------------------------------- #
#  from_dict()                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_from_dict():
    """Test deserialization from dictionary."""
    data = {
        "class": "GeminiTool",
        "tool_id": "test-id",
        "name": "TestGemini",
        "type": "GeminiTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "gemini-2.0-flash-lite",
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
        "structured_output": False,
    }

    tool = await GeminiTool.from_dict(data)

    assert isinstance(tool, GeminiTool)
    assert tool.name == "TestGemini"
    assert tool.model == "gemini-2.0-flash-lite"
    assert tool.system_message == "You are helpful"
    assert tool.chat_params == {"temperature": 0.7}


@pytest.mark.asyncio
async def test_from_dict_roundtrip(gemini_instance):
    """Test that serialization and deserialization are consistent."""
    # Serialize to dict
    data = gemini_instance.to_dict()

    # Deserialize back
    restored = await GeminiTool.from_dict(data)

    # Verify key properties match
    assert restored.name == gemini_instance.name
    assert restored.model == gemini_instance.model
    assert restored.system_message == gemini_instance.system_message
