import asyncio
import os
import uuid
from typing import List

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.runtime import Delta
from grafi.runtime import current_services
from grafi.runtime import deltas_to
from grafi.tools.llms.impl.gemini_tool import GeminiTool
from grafi.tools.tool import Tool
from grafi.topics.topic_types import TopicType

event_store = current_services().event_store
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

    deltas: List[Delta] = []
    content = ""
    with deltas_to(deltas.append):
        messages = await gemini.invoke(
            get_invoke_context(),
            [
                Message(
                    role="user", content="Hello, my name is Grafi, how are you doing?"
                )
            ],
        )
        for message in messages:
            assert message.role == "assistant"
            if isinstance(message.content, str):
                content += message.content
    streamed = "".join(delta.content for delta in deltas)
    print(streamed)
    assert len(deltas) > 1 and streamed == content  # The text, as it came.

    assert content  # non-empty natural-language response (phrasing-independent)
    assert len(await event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  invoke with custom chat params                                            #
# --------------------------------------------------------------------------- #
async def test_gemini_tool_with_chat_param() -> None:
    # Gemini SDK expects a GenerationConfig object – we can pass it as dict
    chat_param = {
        "temperature": 0.1,
        # Gemini 3 thinks first, and its thoughts count towards this limit:
        # one too small for them can leave no answer.
        "max_output_tokens": 1024,
    }

    await event_store.clear_events()
    gemini = GeminiTool.builder().api_key(api_key).chat_params(chat_param).build()

    messages = await gemini.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )
    for message in messages:
        assert message.role == "assistant"
        assert message.content  # non-empty response (phrasing-independent)
        print(message.content)

    assert len(await event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  async one-shot                                                             #
# --------------------------------------------------------------------------- #
async def test_gemini_tool_async() -> None:
    await event_store.clear_events()
    gemini = GeminiTool.builder().api_key(api_key).build()

    content = ""
    messages = await gemini.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )
    for message in messages:
        assert message.role == "assistant"
        if isinstance(message.content, str):
            content += message.content

    print(content)
    assert content  # non-empty natural-language response (phrasing-independent)
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

    assert content  # non-empty natural-language response (phrasing-independent)
    # 2 events from GeminiTool + 2 from Node wrapper
    assert len(await event_store.get_events()) == 4


# --------------------------------------------------------------------------- #
#  Serialization/Deserialization Tests                                        #
# --------------------------------------------------------------------------- #
async def test_gemini_tool_serialization() -> None:
    """Test serialization and deserialization of Gemini tool."""
    await event_store.clear_events()

    # Create original tool
    original_tool = GeminiTool.builder().api_key(api_key).build()

    # Save it as data: its fields, and its class by import path. The key
    # is saved as the name of the variable it comes from, never as itself.
    serialized = original_tool.model_dump(mode="json")
    print(f"Serialized: {serialized}")
    assert serialized["api_key"] == {"env": "GEMINI_API_KEY"}

    # Load it back, as the class it names
    restored_tool = Tool.model_validate(serialized)
    assert isinstance(restored_tool, GeminiTool)
    assert restored_tool.model_dump(mode="json") == serialized

    # Test that the restored tool works correctly
    content = ""
    messages = await restored_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )
    for message in messages:
        assert message.role == "assistant"
        if isinstance(message.content, str):
            content += message.content

    print(content)
    assert content  # non-empty natural-language response (phrasing-independent)
    assert len(await event_store.get_events()) == 2


async def test_gemini_tool_with_chat_param_serialization() -> None:
    """Test serialization with chat params."""
    await event_store.clear_events()

    chat_param = {
        "temperature": 0.1,
        # Gemini 3 thinks first, and its thoughts count towards this limit:
        # one too small for them can leave no answer.
        "max_output_tokens": 1024,
    }

    # Create original tool
    original_tool = (
        GeminiTool.builder().api_key(api_key).chat_params(chat_param).build()
    )

    # Save it as data: its fields, and its class by import path. The key
    # is saved as the name of the variable it comes from, never as itself.
    serialized = original_tool.model_dump(mode="json")
    assert serialized["api_key"] == {"env": "GEMINI_API_KEY"}

    # Load it back, as the class it names
    restored_tool = Tool.model_validate(serialized)
    assert isinstance(restored_tool, GeminiTool)
    assert restored_tool.model_dump(mode="json") == serialized

    # Test that the restored tool works
    messages = await restored_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )
    for message in messages:
        assert message.role == "assistant"
        assert message.content  # non-empty response (phrasing-independent)
        print(message.content)

    assert len(await event_store.get_events()) == 2


asyncio.run(test_gemini_tool_with_chat_param())
asyncio.run(test_gemini_tool_stream())
asyncio.run(test_gemini_tool_async())
asyncio.run(test_llm_stream_node_gemini())
asyncio.run(test_gemini_tool_serialization())
asyncio.run(test_gemini_tool_with_chat_param_serialization())
