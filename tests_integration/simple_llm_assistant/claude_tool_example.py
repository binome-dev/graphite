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
from grafi.tools.llms.impl.claude_tool import ClaudeTool
from grafi.topics.topic_types import TopicType


# --------------------------------------------------------------------------- #
#  Shared helpers / fixtures                                                  #
# --------------------------------------------------------------------------- #
event_store = container.event_store
api_key = os.getenv(
    "ANTHROPIC_API_KEY",
    "",
)


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


# --------------------------------------------------------------------------- #
#  2) async streaming                                                         #
# --------------------------------------------------------------------------- #
async def test_claude_tool_stream() -> None:
    await event_store.clear_events()
    claude = ClaudeTool.builder().is_streaming(True).api_key(api_key).build()

    content = ""
    async for messages in claude.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for msg in messages:
            assert msg.role == "assistant"
            if isinstance(msg.content, str):
                content += msg.content
                print(msg.content + "_", end="", flush=True)

    assert "Grafi" in content
    assert len(await event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  4) invoke with custom chat params                                         #
# --------------------------------------------------------------------------- #
async def test_claude_tool_with_chat_param() -> None:
    # Anthropic needs `max_tokens`; others are optional
    chat_param = {"temperature": 0.2}

    await event_store.clear_events()
    claude = (
        ClaudeTool.builder()
        .api_key(api_key)
        .max_tokens(50)
        .chat_params(chat_param)
        .build()
    )

    async for messages in claude.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for msg in messages:
            assert msg.role == "assistant"
            assert msg.content and "Grafi" in msg.content
            print(msg.content)
            # 30 tokens ≈ < 250 chars for normal prose
            if isinstance(msg.content, str):
                # Ensure the content length is within the expected range
                assert len(msg.content) < 250

    assert len(await event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  5) async one-shot                                                          #
# --------------------------------------------------------------------------- #
async def test_claude_tool_async() -> None:
    await event_store.clear_events()
    claude = ClaudeTool.builder().api_key(api_key).build()

    content = ""
    async for messages in claude.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for msg in messages:
            assert msg.role == "assistant"
            if isinstance(msg.content, str):
                content += msg.content

    print(content)
    assert "Grafi" in content
    assert len(await event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  6) end-to-end pathway through Node                                      #
# --------------------------------------------------------------------------- #
async def test_llm_stream_node_claude() -> None:
    await event_store.clear_events()

    llm_stream_node: Node = (
        Node.builder()
        .tool(ClaudeTool.builder().is_streaming(True).api_key(api_key).build())
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
        for msg in event.data:
            assert msg.role == "assistant"
            if isinstance(msg.content, str):
                content += msg.content
                print(msg.content, end="", flush=True)

    assert "Grafi" in content
    # 2 events from ClaudeTool + 2 from Node decorators
    assert len(await event_store.get_events()) == 4


# --------------------------------------------------------------------------- #
#  Run directly                              #
# --------------------------------------------------------------------------- #

asyncio.run(test_claude_tool_with_chat_param())
asyncio.run(test_claude_tool_stream())
asyncio.run(test_claude_tool_async())
asyncio.run(test_llm_stream_node_claude())
