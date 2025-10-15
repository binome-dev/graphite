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
from grafi.tools.llms.impl.openrouter_tool import OpenRouterTool
from grafi.tools.tool_factory import ToolFactory
from grafi.topics.topic_types import TopicType


event_store = container.event_store
api_key = os.getenv("OPENROUTER_API_KEY", "")  # set your OpenRouter key


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


# --------------------------------------------------------------------------- #
# async streaming                                                             #
# --------------------------------------------------------------------------- #
async def test_openrouter_tool_stream() -> None:
    await event_store.clear_events()
    or_tool = OpenRouterTool.builder().is_streaming(True).api_key(api_key).build()

    content = ""
    async for msgs in or_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for m in msgs:
            assert m.role == "assistant"
            if isinstance(m.content, str):
                content += m.content
                print(m.content + "_", end="", flush=True)

    assert content and "Grafi" in content
    assert len(await event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
# invoke with custom chat params                                             #
# --------------------------------------------------------------------------- #
async def test_openrouter_tool_with_chat_param() -> None:
    chat_param = {"temperature": 0.1, "max_tokens": 120}

    await event_store.clear_events()
    or_tool = OpenRouterTool.builder().api_key(api_key).chat_params(chat_param).build()

    async for msgs in or_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for m in msgs:
            print(m)
            assert m.role == "assistant"
            assert m.content and "Grafi" in m.content
            if isinstance(m.content, str):
                assert len(m.content) < 300

    assert len(await event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
# async one-shot                                                              #
# --------------------------------------------------------------------------- #
async def test_openrouter_tool_async() -> None:
    await event_store.clear_events()
    or_tool = OpenRouterTool.builder().api_key(api_key).build()

    content = ""
    async for messages in or_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for m in messages:
            assert m.role == "assistant"
            if isinstance(m.content, str):
                content += m.content

    print(content)
    assert "Grafi" in content
    assert len(await event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
# end-to-end: Node streaming path                                          #
# --------------------------------------------------------------------------- #
async def test_llm_stream_node_openrouter() -> None:
    await event_store.clear_events()

    llm_stream_node: Node = (
        Node.builder()
        .tool(OpenRouterTool.builder().is_streaming(True).api_key(api_key).build())
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
        for m in event.data:
            assert m.role == "assistant"
            if isinstance(m.content, str):
                content += m.content
                print(m.content, end="", flush=True)

    assert content and "Grafi" in content
    # decorators: 2 events from tool + 2 from node wrapper
    assert len(await event_store.get_events()) == 4


# --------------------------------------------------------------------------- #
#  Serialization/Deserialization Tests                                        #
# --------------------------------------------------------------------------- #
async def test_openrouter_tool_serialization() -> None:
    """Test serialization and deserialization of OpenRouter tool."""
    await event_store.clear_events()

    # Create original tool
    original_tool = OpenRouterTool.builder().api_key(api_key).build()

    # Serialize to dict
    serialized = original_tool.to_dict()
    print(f"Serialized: {serialized}")

    # Deserialize back using ToolFactory
    restored_tool = await ToolFactory.from_dict(serialized)

    # Test that the restored tool works correctly
    content = ""
    async for messages in restored_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for m in messages:
            assert m.role == "assistant"
            if isinstance(m.content, str):
                content += m.content

    print(content)
    assert "Grafi" in content
    assert len(await event_store.get_events()) == 2


async def test_openrouter_tool_with_chat_param_serialization() -> None:
    """Test serialization with chat params."""
    await event_store.clear_events()

    chat_param = {"temperature": 0.1, "max_tokens": 120}

    # Create original tool
    original_tool = (
        OpenRouterTool.builder().api_key(api_key).chat_params(chat_param).build()
    )

    # Serialize to dict
    serialized = original_tool.to_dict()

    # Deserialize back
    restored_tool = await ToolFactory.from_dict(serialized)

    # Test that the restored tool works
    async for messages in restored_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for m in messages:
            print(m)
            assert m.role == "assistant"
            assert m.content and "Grafi" in m.content
            if isinstance(m.content, str):
                assert len(m.content) < 300

    assert len(await event_store.get_events()) == 2


asyncio.run(test_openrouter_tool_with_chat_param())
asyncio.run(test_openrouter_tool_stream())
asyncio.run(test_openrouter_tool_async())
asyncio.run(test_llm_stream_node_openrouter())
asyncio.run(test_openrouter_tool_serialization())
asyncio.run(test_openrouter_tool_with_chat_param_serialization())
