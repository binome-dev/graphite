from typing import Any
from typing import List
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from anthropic import omit
from anthropic.types.text_block import TextBlock
from anthropic.types.tool_use_block import ToolUseBlock
from pydantic_core import PydanticSerializationError

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import Delta
from grafi.runtime import deltas_to
from grafi.tools.llms.impl.claude_tool import ClaudeTool
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


class _Answering:
    """An Anthropic message stream that answers ``response`` whole."""

    def __init__(self, response: Any) -> None:
        self.response = response

    async def __aenter__(self) -> "_Answering":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    @property
    async def text_stream(self) -> Any:
        return
        yield

    async def get_final_message(self) -> Any:
        return self.response


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
    mock_client.messages.stream = Mock(return_value=_Answering(fake_response))

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
    kwargs = mock_client.messages.stream.call_args[1]
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
    mock_client.messages.stream = Mock(return_value=_Answering(fake_response))

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

    kwargs = mock_client.messages.stream.call_args[1]
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
    mock_client.messages.stream.side_effect = _raise

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
#  Saving and loading                                                          #
# --------------------------------------------------------------------------- #
CLAUDE_TOOL = "grafi.tools.llms.impl.claude_tool:ClaudeTool"


@pytest.fixture
def saved_claude(monkeypatch: pytest.MonkeyPatch) -> ClaudeTool:
    """A ClaudeTool with every field set, its key from ANTHROPIC_API_KEY."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_api_key")
    return ClaudeTool(
        name="TestClaude",
        system_message="You are helpful",
        api_key="test_api_key",
        model="claude-sonnet-4-5",
        max_tokens=2048,
        thinking={"type": "enabled", "budget_tokens": 1024},
        effort="high",
        chat_params={"temperature": 0.7},
        is_streaming=False,
    )


def test_dump_names_the_class_and_saves_the_key_as_its_variable(saved_claude):
    assert saved_claude.model_dump(mode="json") == {
        "class": CLAUDE_TOOL,
        "tool_id": saved_claude.tool_id,
        "name": "TestClaude",
        "type": "ClaudeTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "api_key": {"env": "ANTHROPIC_API_KEY"},
        "model": "claude-sonnet-4-5",
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
        "structured_output": False,
        "max_tokens": 2048,
        "thinking": {"type": "enabled", "budget_tokens": 1024},
        "effort": "high",
    }


def test_round_trip(saved_claude):
    data = saved_claude.model_dump(mode="json")

    restored = Tool.model_validate(data)

    assert type(restored) is ClaudeTool
    assert restored.tool_id == saved_claude.tool_id
    assert restored.api_key == "test_api_key"  # Read from ANTHROPIC_API_KEY.
    assert restored.max_tokens == 2048
    assert restored.thinking == {"type": "enabled", "budget_tokens": 1024}
    assert restored.effort == "high"
    assert restored == saved_claude
    assert restored.model_dump(mode="json") == data


def test_load_from_a_manifest_naming_the_class():
    data = {
        "class": CLAUDE_TOOL,
        "tool_id": "test-id",
        "name": "TestClaude",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "claude-haiku-4-5",
        "max_tokens": 2048,
        "thinking": {"type": "adaptive"},
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
    }

    tool = Tool.model_validate(data)

    assert isinstance(tool, ClaudeTool)
    assert tool.tool_id == "test-id"
    assert tool.name == "TestClaude"
    assert tool.model == "claude-haiku-4-5"
    assert tool.max_tokens == 2048
    assert tool.thinking == {"type": "adaptive"}
    assert tool.effort is None
    assert tool.system_message == "You are helpful"
    assert tool.chat_params == {"temperature": 0.7}
    assert tool.is_streaming is False


def test_a_key_not_from_its_variable_is_never_saved(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "the_env_key")
    tool = ClaudeTool(api_key="another_key")

    with pytest.raises(
        PydanticSerializationError, match="ManifestError: .*ClaudeTool.api_key"
    ):
        tool.model_dump(mode="json")


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


@pytest.mark.asyncio
async def test_client_close_failure_does_not_fail_completed_call(
    monkeypatch: pytest.MonkeyPatch,
    claude_instance: ClaudeTool,
    invoke_context: InvokeContext,
) -> None:
    import grafi.tools.llms.impl.claude_tool as cl_module

    fake_block = Mock(TextBlock)
    fake_block.text = "done"
    fake_block.role = "assistant"
    mock_client = MagicMock()
    mock_client.messages.stream = Mock(
        return_value=_Answering(Mock(content=[fake_block]))
    )

    async def mock_aenter(self: Any) -> MagicMock:
        return mock_client

    async def mock_aexit(self: Any, *args: Any) -> None:
        raise OSError("connection pool shutdown failed")

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = mock_aenter
    mock_context_manager.__aexit__ = mock_aexit
    monkeypatch.setattr(
        cl_module, "AsyncAnthropic", MagicMock(return_value=mock_context_manager)
    )

    result = [
        message
        async for batch in claude_instance.invoke(
            invoke_context, [Message(role="user", content="Hi")]
        )
        for message in batch
    ]
    assert [message.content for message in result] == ["done"]


@pytest.mark.asyncio
async def test_stream_close_failure_does_not_fail_the_call(
    monkeypatch: pytest.MonkeyPatch,
    invoke_context: InvokeContext,
) -> None:
    from types import SimpleNamespace

    import grafi.tools.llms.impl.claude_tool as cl_module

    class FakeStream:
        async def __aenter__(self) -> "FakeStream":
            return self

        async def __aexit__(self, *exc_info: Any) -> None:
            raise OSError("stream close failed")

        @property
        async def text_stream(self) -> Any:
            for text in ("a", "b"):
                yield text

        async def get_final_message(self) -> Any:
            return SimpleNamespace(
                content=[TextBlock(type="text", text="ab")], stop_reason="end_turn"
            )

    mock_client = MagicMock()
    mock_client.messages.stream = Mock(return_value=FakeStream())

    async def mock_aenter(self: Any) -> MagicMock:
        return mock_client

    async def mock_aexit(self: Any, *args: Any) -> None:
        return None

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = mock_aenter
    mock_context_manager.__aexit__ = mock_aexit
    monkeypatch.setattr(
        cl_module, "AsyncAnthropic", MagicMock(return_value=mock_context_manager)
    )
    tool = ClaudeTool(api_key="test_api_key")
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


@pytest.mark.asyncio
async def test_a_streamed_answer_is_one_message_with_its_text_and_tool_calls(
    monkeypatch: pytest.MonkeyPatch, invoke_context: InvokeContext
) -> None:
    from types import SimpleNamespace

    import grafi.tools.llms.impl.claude_tool as cl_module

    class FakeStream:
        async def __aenter__(self) -> "FakeStream":
            return self

        async def __aexit__(self, *exc_info: Any) -> None:
            return None

        @property
        async def text_stream(self) -> Any:
            yield "Checking."

        async def get_final_message(self) -> Any:
            return SimpleNamespace(
                content=[
                    TextBlock(type="text", text="Checking."),
                    ToolUseBlock(
                        type="tool_use",
                        id="toolu_1",
                        name="weather",
                        input={"city": "Paris"},
                    ),
                ],
                stop_reason="tool_use",
            )

    client = MagicMock()
    client.messages.stream = Mock(return_value=FakeStream())
    anthropic = MagicMock()
    anthropic.__aenter__ = AsyncMock(return_value=client)
    anthropic.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(cl_module, "AsyncAnthropic", MagicMock(return_value=anthropic))

    tool = ClaudeTool(api_key="test_api_key")
    received: List[Delta] = []
    with deltas_to(received.append):
        batches = [
            batch
            async for batch in tool.invoke(
                invoke_context, [Message(role="user", content="Weather in Paris?")]
            )
        ]

    [[call]] = batches
    assert [delta.content for delta in received] == ["Checking."]
    assert call.content == "Checking."
    assert call.tool_calls[0].id == "toolu_1"
    assert call.tool_calls[0].function.name == "weather"
    assert call.tool_calls[0].function.arguments == '{"city": "Paris"}'


def test_a_reply_without_tool_use_has_no_tool_calls() -> None:
    from types import SimpleNamespace

    response = SimpleNamespace(
        content=[TextBlock(type="text", text="Hello")], stop_reason="end_turn"
    )
    [message] = ClaudeTool(api_key="k").to_messages(response)  # type: ignore[arg-type]
    assert message.content == "Hello"
    assert message.tool_calls is None  # Not [], which routes as a tool call.
