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
async def test_openrouter_tool_a_stream() -> None:
    event_store.clear_events()
    or_tool = OpenRouterTool.builder().is_streaming(True).api_key(api_key).build()

    content = ""
    async for msgs in or_tool.a_invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for m in msgs:
            assert m.role == "assistant"
            if isinstance(m.content, str):
                content += m.content
                print(m.content + "_", end="", flush=True)

    assert content and "Grafi" in content
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
# synchronous one-shot                                                        #
# --------------------------------------------------------------------------- #
def test_openrouter_tool_invoke() -> None:
    event_store.clear_events()
    or_tool = OpenRouterTool.builder().api_key(api_key).build()

    msgs = or_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )

    for m in msgs:
        assert m.role == "assistant"
        assert m.content and "Grafi" in m.content
        print(m.content)

    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
# invoke with custom chat params                                             #
# --------------------------------------------------------------------------- #
def test_openrouter_tool_with_chat_param() -> None:
    chat_param = {"temperature": 0.1, "max_tokens": 15}

    event_store.clear_events()
    or_tool = OpenRouterTool.builder().api_key(api_key).chat_params(chat_param).build()

    msgs = or_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )

    for m in msgs:
        assert m.role == "assistant"
        assert m.content and "Grafi" in m.content
        print(m.content)
        assert len(m.content) < 70  # 15 tokens ≈ < 70 chars

    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
# async one-shot                                                              #
# --------------------------------------------------------------------------- #
async def test_openrouter_tool_async() -> None:
    event_store.clear_events()
    or_tool = OpenRouterTool.builder().api_key(api_key).build()

    content = ""
    async for msgs in or_tool.a_invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for m in msgs:
            assert m.role == "assistant"
            if isinstance(m.content, str):
                content += m.content

    print(content)
    assert "Grafi" in content
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
# end-to-end: Node streaming path                                          #
# --------------------------------------------------------------------------- #
async def test_llm_a_stream_node_openrouter() -> None:
    event_store.clear_events()

    llm_stream_node = (
        Node.builder()
        .tool(OpenRouterTool.builder().is_streaming(True).api_key(api_key).build())
        .build()
    )

    invoke_context = get_invoke_context()
    topic_event = ConsumeFromTopicEvent(
        invoke_context=invoke_context,
        topic_name="test_topic",
        consumer_name="Node",
        consumer_type="Node",
        offset=-1,
        data=[
            Message(role="user", content="Hello, my name is Grafi, how are you doing?")
        ],
    )

    content = ""
    async for msgs in llm_stream_node.a_invoke(invoke_context, [topic_event]):
        for m in msgs:
            assert m.role == "assistant"
            if isinstance(m.content, str):
                content += m.content
                print(m.content, end="", flush=True)

    assert content and "Grafi" in content
    # decorators: 2 events from tool + 2 from node wrapper
    assert len(event_store.get_events()) == 4


# sync
test_openrouter_tool_invoke()
test_openrouter_tool_with_chat_param()

# async
asyncio.run(test_openrouter_tool_a_stream())
asyncio.run(test_openrouter_tool_async())
asyncio.run(test_llm_a_stream_node_openrouter())
