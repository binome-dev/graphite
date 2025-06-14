import asyncio
import os
import uuid

from grafi.common.containers.container import container
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.llms.impl.gemini_tool import GeminiTool
from grafi.tools.llms.llm_stream_response_command import LLMStreamResponseCommand


event_store = container.event_store
api_key = os.getenv("GEMINI_API_KEY", "")  # set your Google AI Studio key here


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


# --------------------------------------------------------------------------- #
#  synchronous streaming                                                      #
# --------------------------------------------------------------------------- #
def test_gemini_tool_stream() -> None:
    event_store.clear_events()
    gemini = GeminiTool.builder().api_key(api_key).build()

    content = ""
    for messages in gemini.stream(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if message.content:
                content += message.content
                print(message.content, end="", flush=True)

    assert content and "Grafi" in content
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  async streaming                                                            #
# --------------------------------------------------------------------------- #
async def test_gemini_tool_a_stream() -> None:
    event_store.clear_events()
    gemini = GeminiTool.builder().api_key(api_key).build()

    content = ""
    async for messages in gemini.a_stream(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if isinstance(message.content, str):
                content += message.content
                print(message.content + "_", end="", flush=True)

    assert content and "Grafi" in content
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  synchronous one-shot                                                       #
# --------------------------------------------------------------------------- #
def test_gemini_tool_execute() -> None:
    event_store.clear_events()
    gemini = GeminiTool.builder().api_key(api_key).build()

    messages = gemini.execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )

    for message in messages:
        assert message.role == "assistant"
        assert message.content and "Grafi" in message.content
        print(message.content)

    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  execute with custom chat params                                            #
# --------------------------------------------------------------------------- #
def test_gemini_tool_with_chat_param() -> None:
    # Gemini SDK expects a GenerationConfig object – we can pass it as dict
    chat_param = {
        "temperature": 0.1,
        "max_output_tokens": 15,
    }

    event_store.clear_events()
    gemini = GeminiTool.builder().api_key(api_key).chat_params(chat_param).build()

    messages = gemini.execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )

    for message in messages:
        assert message.role == "assistant"
        assert message.content and "Grafi" in message.content
        print(message.content)
        # 15 tokens ~ < 120 chars in normal language
        assert len(message.content) < 150

    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  async one-shot                                                             #
# --------------------------------------------------------------------------- #
async def test_gemini_tool_async() -> None:
    event_store.clear_events()
    gemini = GeminiTool.builder().api_key(api_key).build()

    content = ""
    async for messages in gemini.a_execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if isinstance(message.content, str):
                content += message.content

    print(content)
    assert "Grafi" in content
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  LLMNode end-to-end streaming path                                          #
# --------------------------------------------------------------------------- #
async def test_llm_a_stream_node_gemini() -> None:
    event_store.clear_events()

    llm_stream_node = (
        LLMNode.builder()
        .command(
            LLMStreamResponseCommand.builder()
            .llm(GeminiTool.builder().api_key(api_key).build())
            .build()
        )
        .build()
    )

    execution_context = get_execution_context()
    topic_event = ConsumeFromTopicEvent(
        execution_context=execution_context,
        topic_name="test_topic",
        consumer_name="LLMNode",
        consumer_type="LLMNode",
        offset=-1,
        data=[
            Message(role="user", content="Hello, my name is Grafi, how are you doing?")
        ],
    )

    content = ""
    async for messages in llm_stream_node.a_execute(execution_context, [topic_event]):
        for message in messages:
            assert message.role == "assistant"
            if isinstance(message.content, str):
                content += message.content
                print(message.content, end="", flush=True)

    assert content and "Grafi" in content
    # 2 events from GeminiTool + 2 from LLMNode wrapper
    assert len(event_store.get_events()) == 4


# synchronous tests
test_gemini_tool_stream()
test_gemini_tool_execute()
test_gemini_tool_with_chat_param()

# async tests
asyncio.run(test_gemini_tool_a_stream())
asyncio.run(test_gemini_tool_async())
asyncio.run(test_llm_a_stream_node_gemini())
