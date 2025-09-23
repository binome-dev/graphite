import asyncio
import os
import uuid

from grafi.common.containers.container import container
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.tools.llms.impl.gemini_tool import GeminiTool
from grafi.topics.topic_types import TopicType


event_store = container.event_store
api_key = os.getenv("GEMINI_API_KEY", "")  # set your Google AI Studio key here


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


# --------------------------------------------------------------------------- #
#  async streaming                                                            #
# --------------------------------------------------------------------------- #
async def test_gemini_tool_stream() -> None:
    await event_store.clear_events()
    gemini = GeminiTool.builder().is_streaming(True).api_key(api_key).build()

    content = ""
    async for messages in gemini.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if isinstance(message.content, str):
                content += message.content
                print(message.content + "_", end="", flush=True)

    assert content and "Grafi" in content
    assert len(await event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  invoke with custom chat params                                            #
# --------------------------------------------------------------------------- #
async def test_gemini_tool_with_chat_param() -> None:
    # Gemini SDK expects a GenerationConfig object – we can pass it as dict
    chat_param = {
        "temperature": 0.1,
        "max_output_tokens": 15,
    }

    await event_store.clear_events()
    gemini = GeminiTool.builder().api_key(api_key).chat_params(chat_param).build()

    async for messages in gemini.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            assert message.content and "Grafi" in message.content
            print(message.content)
            # 15 tokens ~ < 120 chars in normal language
            if isinstance(message.content, str):
                # Ensure the content length is within the expected range
                assert len(message.content) < 150

    assert len(await event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  async one-shot                                                             #
# --------------------------------------------------------------------------- #
async def test_gemini_tool_async() -> None:
    await event_store.clear_events()
    gemini = GeminiTool.builder().api_key(api_key).build()

    content = ""
    async for messages in gemini.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if isinstance(message.content, str):
                content += message.content

    print(content)
    assert "Grafi" in content
    assert len(await event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  Node end-to-end streaming path                                          #
# --------------------------------------------------------------------------- #
async def test_llm_stream_node_gemini() -> None:
    await event_store.clear_events()

    llm_stream_node: Node = (
        Node.builder()
        .tool(GeminiTool.builder().is_streaming(True).api_key(api_key).build())
        .build()
    )

    invoke_context = get_invoke_context()
    topic_event = ConsumeFromTopicEvent(
        invoke_context=invoke_context,
        name="test_topic",
        type=TopicType.DEFAULT_TOPIC_TYPE,
        consumer_name="Node",
        consumer_type="Node",
        offset=-1,
        data=[
            Message(role="user", content="Hello, my name is Grafi, how are you doing?")
        ],
    )

    content = ""
    async for event in llm_stream_node.invoke(invoke_context, [topic_event]):
        for message in event.data:
            assert message.role == "assistant"
            if isinstance(message.content, str):
                content += message.content
                print(message.content, end="", flush=True)

    assert content and "Grafi" in content
    # 2 events from GeminiTool + 2 from Node wrapper
    assert len(await event_store.get_events()) == 4


asyncio.run(test_gemini_tool_with_chat_param())
asyncio.run(test_gemini_tool_stream())
asyncio.run(test_gemini_tool_async())
asyncio.run(test_llm_stream_node_gemini())
