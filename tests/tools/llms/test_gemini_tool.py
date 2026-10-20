import asyncio
import base64
import json
from typing import AsyncIterator
from typing import List
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from google.genai.types import FunctionCall
from google.genai.types import GenerateContentResponse
from google.genai.types import Part
from pydantic_core import PydanticSerializationError

from grafi.common.events.event_codec import default_event_codec
from grafi.common.exceptions import LLMToolException
from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import Delta
from grafi.runtime import deltas_to
from grafi.tools.llms.impl.gemini_tool import GeminiTool
from grafi.tools.tool import Tool


def _response(*parts: Part) -> GenerateContentResponse:
    return GenerateContentResponse.model_validate(
        {"candidates": [{"content": {"role": "model", "parts": parts}}]}
    )


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
        model="gemini-3.5-flash",
    )


# --------------------------------------------------------------------------- #
#  Basic initialisation
# --------------------------------------------------------------------------- #
def test_init(gemini_instance):
    assert gemini_instance.api_key == "test_api_key"
    assert gemini_instance.model == "gemini-3.5-flash"
    assert gemini_instance.system_message == "dummy system message"


# --------------------------------------------------------------------------- #
#  invoke() — simple reply
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_simple_response(monkeypatch, gemini_instance, invoke_context):
    import grafi.tools.llms.impl.gemini_tool as gm_module

    mock_response = _response(Part(text="Hello, world!"))

    # Stub client and method - need to mock the async aio interface
    mock_client = MagicMock()
    mock_client.aio.aclose = AsyncMock()
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
    assert call_kwargs["model"] == "gemini-3.5-flash"

    # System prompt is delivered via config.system_instruction (SDK-native),
    # not faked as a leading user turn; contents holds only the real turns.
    assert call_kwargs["config"].system_instruction == "dummy system message"
    assert call_kwargs["contents"][0].role == "user"
    assert call_kwargs["contents"][0].parts[0].text == "Say hello"


# --------------------------------------------------------------------------- #
#  invoke() — tool / function call path
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_function_call(monkeypatch, gemini_instance, invoke_context):
    import grafi.tools.llms.impl.gemini_tool as gm_module

    mock_response = _response(
        Part(
            function_call=FunctionCall(
                id="function_call_id", name="get_weather", args={"location": "London"}
            )
        )
    )

    mock_client = MagicMock()
    mock_client.aio.aclose = AsyncMock()
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

    [[message]] = [
        batch async for batch in gemini_instance.invoke(invoke_context, input_data)
    ]
    [call] = message.tool_calls
    assert (call.id, call.function.name) == ("function_call_id", "get_weather")
    assert call.function.arguments == '{"location": "London"}'

    config = mock_client.aio.models.generate_content.call_args[1]["config"]
    [declaration] = config.tools[0].function_declarations
    assert declaration.name == "get_weather"


# --------------------------------------------------------------------------- #
#  Error propagation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_api_error(monkeypatch, gemini_instance, invoke_context):
    import grafi.tools.llms.impl.gemini_tool as gm_module

    def _raise(*_a, **_kw):  # pragma: no cover
        raise Exception("Failure")

    mock_client = MagicMock()
    mock_client.aio.aclose = AsyncMock()
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

    contents, tools, system_instruction = gemini_instance.prepare_api_input(msgs)

    # System text (instance message + system-role message) is hoisted out of
    # contents into system_instruction; contents holds only user/model turns.
    assert system_instruction == "dummy system message\n\nYou are helpful."
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "Hello!"
    assert contents[-1].role == "model"
    assert tools == [] or tools is None


# --------------------------------------------------------------------------- #
#  Saving and loading                                                          #
# --------------------------------------------------------------------------- #
GEMINI_TOOL = "grafi.tools.llms.impl.gemini_tool:GeminiTool"


@pytest.fixture
def saved_gemini(monkeypatch: pytest.MonkeyPatch) -> GeminiTool:
    """A GeminiTool with every field set, its key from GEMINI_API_KEY."""
    monkeypatch.setenv("GEMINI_API_KEY", "test_api_key")
    return GeminiTool(
        name="TestGemini",
        system_message="You are helpful",
        api_key="test_api_key",
        model="gemini-3.5-pro",
        thinking_budget=128,
        chat_params={"temperature": 0.7},
        is_streaming=False,
    )


def test_dump_names_the_class_and_saves_the_key_as_its_variable(saved_gemini):
    assert saved_gemini.model_dump(mode="json") == {
        "class": GEMINI_TOOL,
        "tool_id": saved_gemini.tool_id,
        "name": "TestGemini",
        "type": "GeminiTool",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "api_key": {"env": "GEMINI_API_KEY"},
        "model": "gemini-3.5-pro",
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
        "structured_output": False,
        "thinking_budget": 128,
    }


def test_round_trip(saved_gemini):
    data = saved_gemini.model_dump(mode="json")

    restored = Tool.model_validate(data)

    assert type(restored) is GeminiTool
    assert restored.tool_id == saved_gemini.tool_id
    assert restored.api_key == "test_api_key"  # Read from GEMINI_API_KEY.
    assert restored.thinking_budget == 128
    assert restored == saved_gemini
    assert restored.model_dump(mode="json") == data


def test_load_from_a_manifest_naming_the_class():
    data = {
        "class": GEMINI_TOOL,
        "tool_id": "test-id",
        "name": "TestGemini",
        "oi_span_type": "LLM",
        "system_message": "You are helpful",
        "model": "gemini-3.5-flash",
        "chat_params": {"temperature": 0.7},
        "is_streaming": False,
    }

    tool = Tool.model_validate(data)

    assert isinstance(tool, GeminiTool)
    assert tool.tool_id == "test-id"
    assert tool.name == "TestGemini"
    assert tool.model == "gemini-3.5-flash"
    assert tool.thinking_budget is None
    assert tool.system_message == "You are helpful"
    assert tool.chat_params == {"temperature": 0.7}


def test_a_key_not_from_its_variable_is_never_saved(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "the_env_key")
    tool = GeminiTool(api_key="another_key")

    with pytest.raises(
        PydanticSerializationError, match="ManifestError: .*GeminiTool.api_key"
    ):
        tool.model_dump(mode="json")


# --------------------------------------------------------------------------- #
#  thinking_budget mapped into GenerateContentConfig                           #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_invoke_thinking_budget(monkeypatch, invoke_context):
    import grafi.tools.llms.impl.gemini_tool as gm_module

    tool = GeminiTool(
        api_key="test_api_key", model="gemini-3.5-flash", thinking_budget=128
    )

    mock_response = _response(Part(text="hi"))

    mock_client = MagicMock()
    mock_client.aio.aclose = AsyncMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    monkeypatch.setattr(
        gm_module, "genai", MagicMock(Client=MagicMock(return_value=mock_client))
    )

    async for _ in tool.invoke(invoke_context, [Message(role="user", content="hi")]):
        pass

    cfg = mock_client.aio.models.generate_content.call_args[1]["config"]
    assert cfg.thinking_config is not None
    assert cfg.thinking_config.thinking_budget == 128


def _streaming(
    monkeypatch: pytest.MonkeyPatch, chunks: AsyncIterator[GenerateContentResponse]
) -> MagicMock:
    """A patched client streaming ``chunks``."""
    import grafi.tools.llms.impl.gemini_tool as gm_module

    mock_client = MagicMock()
    mock_client.aio.aclose = AsyncMock()
    mock_client.aio.models.generate_content_stream = AsyncMock(return_value=chunks)
    monkeypatch.setattr(
        gm_module, "genai", MagicMock(Client=MagicMock(return_value=mock_client))
    )
    return mock_client


async def _cancelled_after_the_first_delta(
    tool: GeminiTool, invoke_context: InvokeContext
) -> None:
    first = asyncio.Event()

    async def call() -> None:
        with deltas_to(lambda delta: first.set()):
            async for _ in tool.invoke(
                invoke_context, [Message(role="user", content="Hi")]
            ):
                pass

    task = asyncio.create_task(call())
    async with asyncio.timeout(5):
        await first.wait()
        task.cancel()
        await asyncio.wait({task})
    assert task.cancelled()


@pytest.mark.asyncio
async def test_a_call_cancelled_mid_stream_releases_the_stream_and_client(
    monkeypatch: pytest.MonkeyPatch, invoke_context: InvokeContext
) -> None:
    closed: List[str] = []

    async def chunks() -> AsyncIterator[GenerateContentResponse]:
        try:
            yield _response(Part(text="a"))
            await asyncio.Event().wait()
        finally:
            closed.append("stream")

    mock_client = _streaming(monkeypatch, chunks())
    mock_client.aio.aclose.side_effect = lambda: closed.append("aio")
    mock_client.close = Mock(side_effect=lambda: closed.append("client"))
    await _cancelled_after_the_first_delta(GeminiTool(api_key="k"), invoke_context)
    assert closed == ["stream", "aio", "client"]


@pytest.mark.asyncio
async def test_a_stream_failing_to_close_does_not_replace_the_calls_error(
    monkeypatch: pytest.MonkeyPatch, invoke_context: InvokeContext
) -> None:
    async def chunks() -> AsyncIterator[GenerateContentResponse]:
        try:
            yield _response(Part(text="a"))
            yield _response(Part(text="b"))
        finally:
            raise OSError("stream close failed")

    def receive(delta: Delta) -> None:
        raise ValueError("caller gone")

    mock_client = _streaming(monkeypatch, chunks())
    with deltas_to(receive), pytest.raises(LLMToolException) as raised:
        async for _ in GeminiTool(api_key="k").invoke(
            invoke_context, [Message(role="user", content="Hi")]
        ):
            pass
    assert isinstance(raised.value.__cause__, ValueError)
    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_client_close_failure_does_not_fail_completed_call(
    monkeypatch: pytest.MonkeyPatch, invoke_context: InvokeContext
) -> None:
    import grafi.tools.llms.impl.gemini_tool as gm_module

    response = _response(Part(text="done"))
    mock_client = MagicMock()
    mock_client.aio.aclose = AsyncMock(side_effect=OSError("close"))
    mock_client.aio.models.generate_content = AsyncMock(return_value=response)
    monkeypatch.setattr(
        gm_module, "genai", MagicMock(Client=MagicMock(return_value=mock_client))
    )
    tool = GeminiTool(api_key="test_api_key")
    result = [
        message
        async for batch in tool.invoke(
            invoke_context, [Message(role="user", content="Hi")]
        )
        for message in batch
    ]
    assert [message.content for message in result] == ["done"]
    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_config_creates_no_client(
    monkeypatch: pytest.MonkeyPatch, invoke_context: InvokeContext
) -> None:
    import grafi.tools.llms.impl.gemini_tool as gm_module

    client_factory = MagicMock()
    monkeypatch.setattr(gm_module, "genai", MagicMock(Client=client_factory))
    tool = GeminiTool(api_key="test_api_key", chat_params={"not_a_field": 1})
    with pytest.raises(Exception):
        async for _ in tool.invoke(
            invoke_context, [Message(role="user", content="Hi")]
        ):
            pass
    client_factory.assert_not_called()


@pytest.mark.asyncio
async def test_a_cancelled_client_close_does_not_replace_an_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    gemini_instance: GeminiTool,
    invoke_context: InvokeContext,
) -> None:
    # Regression: the per-call client was closed in a plain finally, so a
    # cancellation raised while closing it replaced an interrupt already
    # propagating.
    import asyncio

    import grafi.tools.llms.impl.gemini_tool as gm_module

    def interrupted(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt()

    mock_client = MagicMock()
    mock_client.aio.aclose = AsyncMock(side_effect=asyncio.CancelledError())
    mock_client.aio.models.generate_content.side_effect = interrupted
    monkeypatch.setattr(
        gm_module, "genai", MagicMock(Client=MagicMock(return_value=mock_client))
    )
    with pytest.raises(KeyboardInterrupt) as raised:
        async for _ in gemini_instance.invoke(
            invoke_context, [Message(role="user", content="Hi")]
        ):
            pass
    assert any("CancelledError" in note for note in raised.value.__notes__)


def test_history_keeps_function_calls_and_their_named_responses(gemini_instance):
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
    }
    contents, _, _ = gemini_instance.prepare_api_input(
        [
            Message(role="user", content="Weather?"),
            Message(role="assistant", content="", tool_calls=[call]),
            Message(role="tool", tool_call_id="call_1", content="sunny"),
        ]
    )
    asked, called, answered = contents
    assert called.role == "model"
    assert called.parts[0].function_call.name == "get_weather"
    assert called.parts[0].function_call.args == {"city": "Paris"}
    assert answered.role == "user"
    response = answered.parts[0].function_response
    assert (response.name, response.response) == ("get_weather", {"result": "sunny"})


@pytest.mark.asyncio
async def test_a_streamed_answer_is_one_message_keeping_its_calls_signatures(
    monkeypatch, gemini_instance, invoke_context
):
    call = FunctionCall(id="call_1", name="get_weather", args={"city": "Paris"})

    async def chunks() -> AsyncIterator[GenerateContentResponse]:
        yield _response(Part(text="Thinking...", thought=True))
        yield _response(Part(text="Checking."))
        yield _response(Part(function_call=call, thought_signature=b"sig"))

    _streaming(monkeypatch, chunks())
    received: List[Delta] = []
    with deltas_to(received.append):
        [[message]] = [
            batch
            async for batch in gemini_instance.invoke(
                invoke_context, [Message(role="user", content="Weather in Paris?")]
            )
        ]

    assert received == [Delta("Checking.")]  # Thoughts are not the answer.
    assert message.content == "Checking."
    [tool_call] = message.tool_calls
    assert tool_call.function.name == "get_weather"
    assert tool_call.function.arguments == '{"city": "Paris"}'
    # Kept as Gemini's OpenAI-compatible API keeps it, and sent back with the
    # call, as Gemini 3 requires.
    assert tool_call.model_extra["extra_content"] == {
        "google": {"thought_signature": base64.b64encode(b"sig").decode()}
    }
    contents, _, _ = gemini_instance.prepare_api_input([message])
    [text, sent] = contents[0].parts
    assert (sent.function_call.name, sent.thought_signature) == ("get_weather", b"sig")


def test_a_reply_without_text_or_calls_is_empty_not_a_placeholder(gemini_instance):
    [message] = gemini_instance.to_messages(GenerateContentResponse())
    assert message.content == "" and message.tool_calls is None


def test_a_signature_survives_the_event_store_and_an_unsigned_call_gets_the_skip(
    gemini_instance,
):
    from grafi.common.events.topic_events.publish_to_topic_event import (
        PublishToTopicEvent,
    )

    [signed] = gemini_instance.to_messages(
        _response(
            Part(
                function_call=FunctionCall(id="a", name="f", args={}),
                thought_signature=b"sig",
            ),
            Part(function_call=FunctionCall(id="b", name="f", args={})),
        )
    )
    stored = PublishToTopicEvent(
        invoke_context=InvokeContext(
            conversation_id="c", invoke_id="i", assistant_request_id="r"
        ),
        data=[signed],
    )
    encoded = json.loads(json.dumps(default_event_codec.encode(stored)))
    [restored] = default_event_codec.decode(encoded).data
    # Another provider's call carries no signature; Gemini 3 needs one on the
    # first call of each answer, which then gets the documented skip value.
    unsigned = Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "x",
                    "type": "function",
                    "function": {"name": "f", "arguments": "{}"},
                },
                {
                    "id": "y",
                    "type": "function",
                    "function": {"name": "f", "arguments": "{}"},
                },
            ],
        }
    )
    contents, _, _ = gemini_instance.prepare_api_input([restored, unsigned])
    assert [part.thought_signature for part in contents[0].parts] == [b"sig", None]
    assert [part.thought_signature for part in contents[1].parts] == [
        b"skip_thought_signature_validator",
        None,
    ]


def test_a_blocked_prompt_or_answer_is_a_refusal(gemini_instance):
    blocked = GenerateContentResponse.model_validate(
        {"prompt_feedback": {"block_reason": "SAFETY"}}
    )
    stopped = GenerateContentResponse.model_validate(
        {"candidates": [{"finish_reason": "RECITATION"}]}
    )
    [message] = gemini_instance.to_messages(blocked)
    assert message.refusal == "Prompt blocked by Gemini: SAFETY"
    [message] = gemini_instance.to_messages(stopped)
    assert message.refusal == "Answer stopped by Gemini: RECITATION"
    [message] = gemini_instance.to_messages(_response(Part(text="fine")))
    assert message.refusal is None
