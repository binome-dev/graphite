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
from grafi.tools.llms.impl.openrouter_tool import OpenRouterTool
from grafi.tools.llms.llm_stream_response_command import LLMStreamResponseCommand


event_store = container.event_store
api_key = os.getenv("OPENROUTER_API_KEY", "")  # set your OpenRouter key


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


# --------------------------------------------------------------------------- #
# synchronous streaming                                                       #
# --------------------------------------------------------------------------- #
def test_openrouter_tool_stream() -> None:
    event_store.clear_events()
    or_tool = OpenRouterTool.builder().api_key(api_key).build()

    content = ""
    for msgs in or_tool.stream(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for m in msgs:
            assert m.role == "assistant"
            if m.content:
                content += m.content
                print(m.content, end="", flush=True)

    assert content and "Grafi" in content
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
# async streaming                                                             #
# --------------------------------------------------------------------------- #
async def test_openrouter_tool_a_stream() -> None:
    event_store.clear_events()
    or_tool = OpenRouterTool.builder().api_key(api_key).build()

    content = ""
    async for msgs in or_tool.a_stream(
        get_execution_context(),
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
def test_openrouter_tool_execute() -> None:
    event_store.clear_events()
    or_tool = OpenRouterTool.builder().api_key(api_key).build()

    msgs = or_tool.execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )

    for m in msgs:
        assert m.role == "assistant"
        assert m.content and "Grafi" in m.content
        print(m.content)

    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
# execute with custom chat params                                             #
# --------------------------------------------------------------------------- #
def test_openrouter_tool_with_chat_param() -> None:
    chat_param = {"temperature": 0.1, "max_tokens": 15}

    event_store.clear_events()
    or_tool = OpenRouterTool.builder().api_key(api_key).chat_params(chat_param).build()

    msgs = or_tool.execute(
        get_execution_context(),
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
    async for msgs in or_tool.a_execute(
        get_execution_context(),
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
# end-to-end: LLMNode streaming path                                          #
# --------------------------------------------------------------------------- #
async def test_llm_a_stream_node_openrouter() -> None:
    event_store.clear_events()

    llm_stream_node = (
        LLMNode.builder()
        .command(
            LLMStreamResponseCommand.builder()
            .llm(OpenRouterTool.builder().api_key(api_key).build())
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
    async for msgs in llm_stream_node.a_execute(execution_context, [topic_event]):
        for m in msgs:
            assert m.role == "assistant"
            if isinstance(m.content, str):
                content += m.content
                print(m.content, end="", flush=True)

    assert content and "Grafi" in content
    # decorators: 2 events from tool + 2 from node wrapper
    assert len(event_store.get_events()) == 4


# sync
test_openrouter_tool_stream()
test_openrouter_tool_execute()
test_openrouter_tool_with_chat_param()

# async
asyncio.run(test_openrouter_tool_a_stream())
asyncio.run(test_openrouter_tool_async())
asyncio.run(test_llm_a_stream_node_openrouter())
