from typing import List
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from anthropic import omit
from anthropic.types.text_block import TextBlock

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.llms.impl.claude_tool import ClaudeTool


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
def claude_instance() -> ClaudeTool:
    return ClaudeTool(
        system_message="dummy system message",
        name="ClaudeTool",
        api_key="test_api_key",
        model="claude-haiku-4-5",
        max_tokens=2048,
    )


# --------------------------------------------------------------------------- #
#  Basic initialisation
# --------------------------------------------------------------------------- #
def test_init(claude_instance):
    assert claude_instance.api_key == "test_api_key"
    assert claude_instance.model == "claude-haiku-4-5"
    assert claude_instance.system_message == "dummy system message"
    assert claude_instance.max_tokens == 2048


# --------------------------------------------------------------------------- #
#  invoke() – simple assistant response
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_simple_response(monkeypatch, claude_instance, invoke_context):
    import grafi.tools.llms.impl.claude_tool as cl_module

    # fake AnthropicMessage: .content is list of blocks that each have .text
    fake_block = Mock(TextBlock)
    fake_block.text = "Hello, world!"
    fake_block.role = "assistant"
    fake_response = Mock(content=[fake_block])

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=fake_response)

    # Create async context manager mock for AsyncAnthropic
    async def mock_aenter(self):
        return mock_client

    async def mock_aexit(self, *args):
        pass

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = mock_aenter
    mock_context_manager.__aexit__ = mock_aexit

    # patch AsyncAnthropic constructor to return context manager
    mock_async_anthropic_cls = MagicMock(return_value=mock_context_manager)
    monkeypatch.setattr(cl_module, "AsyncAnthropic", mock_async_anthropic_cls)

    input_data = [Message(role="user", content="Say hello")]
    result = []
    async for messages in claude_instance.invoke(invoke_context, input_data):
        result.extend(messages)

    assert isinstance(result, List)
    assert result[0].role == "assistant"
    assert result[0].content == "Hello, world!"

    # verify constructor args
    mock_async_anthropic_cls.assert_called_once_with(api_key="test_api_key")

    # verify create() called with right kwargs
    kwargs = mock_client.messages.create.call_args[1]
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["max_tokens"] == 2048
    # system prompt must be the top-level `system=` param, NOT a message role
    assert kwargs["system"] == "dummy system message"
    assert all(msg["role"] != "system" for msg in kwargs["messages"])
    assert kwargs["messages"][0]["role"] == "user"
    assert kwargs["messages"][0]["content"] == "Say hello"
    # no tools in this call
    assert kwargs["tools"] is omit


# --------------------------------------------------------------------------- #
#  invoke() – function / tool call path
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_function_call(monkeypatch, claude_instance, invoke_context):
    import grafi.tools.llms.impl.claude_tool as cl_module

    fake_block = Mock()
    fake_block.text = ""  # content empty when tool chosen
    fake_response = Mock(content=[fake_block])

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=fake_response)

    # Create async context manager mock for AsyncAnthropic
    async def mock_aenter(self):
        return mock_client

    async def mock_aexit(self, *args):
        pass

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = mock_aenter
    mock_context_manager.__aexit__ = mock_aexit

    mock_async_anthropic_cls = MagicMock(return_value=mock_context_manager)
    monkeypatch.setattr(cl_module, "AsyncAnthropic", mock_async_anthropic_cls)

    tools = [
        FunctionSpec(
            name="get_weather",
            description="Get weather",
            parameters=ParametersSchema(
                type="object",
                properties={"location": ParameterSchema(type="string")},
            ),
        )  # same schema shape; Claude only needs .function
    ]

    msgs = [Message(role="user", content="Weather?")]
    claude_instance.add_function_specs(tools)
    async for _ in claude_instance.invoke(invoke_context, msgs):
        pass  # Just consume the generator to trigger the API call

    kwargs = mock_client.messages.create.call_args[1]
    assert kwargs["tools"] is not None


# --------------------------------------------------------------------------- #
#  Error propagation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_api_error(monkeypatch, claude_instance, invoke_context):
    import grafi.tools.llms.impl.claude_tool as cl_module

    def _raise(*_a, **_kw):  # pragma: no cover
        raise Exception("Boom")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _raise

    # Create async context manager mock for AsyncAnthropic
    async def mock_aenter(self):
        return mock_client

    async def mock_aexit(self, *args):
        pass

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = mock_aenter
    mock_context_manager.__aexit__ = mock_aexit

    mock_async_anthropic_cls = MagicMock(return_value=mock_context_manager)
    monkeypatch.setattr(cl_module, "AsyncAnthropic", mock_async_anthropic_cls)

    from grafi.common.exceptions import LLMToolException

    with pytest.raises(LLMToolException, match="Anthropic async call failed"):
        async for _ in claude_instance.invoke(
            invoke_context, [Message(role="user", content="Hi")]
        ):
            pass  # Exception should be raised before we get any results


# --------------------------------------------------------------------------- #
#  prepare_api_input helper
# --------------------------------------------------------------------------- #
def test_prepare_api_input(claude_instance):
    msgs = [
        Message(role="system", content="You are helpful."),
        Message(role="user", content="Hello!"),
        Message(role="assistant", content="Hi."),
    ]
    system, api_messages, api_tools = claude_instance.prepare_api_input(msgs)

    # System prompt is returned separately (instance message + system-role msg),
    # never injected into the messages array.
    assert system == "dummy system message\n\nYou are helpful."
    assert all(m["role"] in ("user", "assistant") for m in api_messages)
    assert api_messages[0]["role"] == "user"
    assert api_messages[0]["content"] == "Hello!"
    assert api_messages[-1]["role"] == "assistant"
    assert api_tools is omit


def test_prepare_api_input_tool_call_linkage(claude_instance):
    """Assistant tool_calls and tool results map to tool_use/tool_result blocks."""
    from openai.types.chat.chat_completion_message_tool_call import (
        ChatCompletionMessageToolCall,
    )
    from openai.types.chat.chat_completion_message_tool_call import Function

    tool_call = ChatCompletionMessageToolCall(
        id="call_123",
        type="function",
        function=Function(name="get_weather", arguments='{"location": "Paris"}'),
    )
    msgs = [
        Message(role="user", content="Weather in Paris?"),
        Message(role="assistant", content="", tool_calls=[tool_call]),
        Message(role="tool", tool_call_id="call_123", content="20C and sunny"),
    ]
    _system, api_messages, _tools = claude_instance.prepare_api_input(msgs)

    # assistant turn carries a tool_use block
    assistant_turn = api_messages[1]
    assert assistant_turn["role"] == "assistant"
    use_block = assistant_turn["content"][0]
    assert use_block["type"] == "tool_use"
    assert use_block["id"] == "call_123"
    assert use_block["name"] == "get_weather"
    assert use_block["input"] == {"location": "Paris"}

    # tool result becomes a user turn carrying a tool_result block
    tool_turn = api_messages[2]
    assert tool_turn["role"] == "user"
    result_block = tool_turn["content"][0]
    assert result_block["type"] == "tool_result"
    assert result_block["tool_use_id"] == "call_123"
    assert result_block["content"] == "20C and sunny"


# --------------------------------------------------------------------------- #
#  to_dict                                                                     #
# --------------------------------------------------------------------------- #
def test_to_dict(claude_instance):
    d = claude_instance.to_dict()
    assert d["name"] == "ClaudeTool"
    assert d["type"] == "ClaudeTool"
    assert d["api_key"] == "****************"
    assert d["model"] == "claude-haiku-4-5"


# --------------------------------------------------------------------------- #
#  from_dict                                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_from_dict():
    """Test deserialization from dictionary."""
    data = {
        "class": "ClaudeTool",
        "tool_id": "test-id",
        "name": "TestClaude",
        "type": "ClaudeTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "claude-haiku-4-5",
        "max_tokens": 2048,
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
        "structured_output": False,
    }

    tool = await ClaudeTool.from_dict(data)

    assert isinstance(tool, ClaudeTool)
    assert tool.name == "TestClaude"
    assert tool.model == "claude-haiku-4-5"
    assert tool.max_tokens == 2048
    assert tool.system_message == "You are helpful"
    assert tool.chat_params == {"temperature": 0.7}
    assert tool.is_streaming is False
    assert tool.structured_output is False


@pytest.mark.asyncio
async def test_from_dict_roundtrip(claude_instance):
    """Test that serialization and deserialization are consistent."""
    # Serialize to dict
    data = claude_instance.to_dict()

    # Deserialize back
    restored = await ClaudeTool.from_dict(data)

    # Verify key properties match
    assert restored.name == claude_instance.name
    assert restored.model == claude_instance.model
    assert restored.max_tokens == claude_instance.max_tokens
    assert restored.system_message == claude_instance.system_message
    assert restored.chat_params == claude_instance.chat_params
    assert restored.is_streaming == claude_instance.is_streaming


# --------------------------------------------------------------------------- #
#  thinking / effort request assembly                                          #
# --------------------------------------------------------------------------- #
def test_request_kwargs_thinking_and_effort():
    tool = ClaudeTool(
        api_key="k",
        model="claude-haiku-4-5",
        max_tokens=1000,
        thinking={"type": "adaptive"},
        effort="high",
        chat_params={"output_config": {"foo": "bar"}, "service_tier": "auto"},
    )
    kwargs = tool._request_kwargs(omit, [], omit)

    assert kwargs["thinking"] == {"type": "adaptive"}
    # effort is folded into output_config, merged with the caller-supplied one.
    assert kwargs["output_config"]["effort"] == "high"
    assert kwargs["output_config"]["foo"] == "bar"
    # other chat_params still pass through.
    assert kwargs["service_tier"] == "auto"


def test_request_kwargs_omits_unset_fields():
    tool = ClaudeTool(api_key="k", model="claude-haiku-4-5", max_tokens=1000)
    kwargs = tool._request_kwargs(omit, [], omit)
    assert "thinking" not in kwargs
    assert "output_config" not in kwargs


# --------------------------------------------------------------------------- #
#  refusal stop reason                                                         #
# --------------------------------------------------------------------------- #
def test_to_messages_refusal(claude_instance):
    resp = Mock(
        content=[],
        stop_reason="refusal",
        stop_details=Mock(explanation="declined for policy reasons"),
    )
    messages = claude_instance.to_messages(resp)
    assert messages[0].refusal == "declined for policy reasons"
    assert messages[0].content == ""
