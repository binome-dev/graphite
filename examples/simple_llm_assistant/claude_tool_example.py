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
from grafi.tools.llms.impl.claude_tool import ClaudeTool
from grafi.tools.llms.llm_stream_response_command import LLMStreamResponseCommand


# --------------------------------------------------------------------------- #
#  Shared helpers / fixtures                                                  #
# --------------------------------------------------------------------------- #
event_store = container.event_store
api_key = os.getenv("ANTHROPIC_API_KEY", "")


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


# --------------------------------------------------------------------------- #
#  1) synchronous streaming                                                   #
# --------------------------------------------------------------------------- #
def test_claude_tool_stream() -> None:
    event_store.clear_events()
    claude = ClaudeTool.builder().api_key(api_key).build()

    content = ""
    for messages in claude.stream(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for msg in messages:
            assert msg.role == "assistant"
            if msg.content:
                content += msg.content
                print(msg.content, end="", flush=True)

    print("\n")

    assert "Grafi" in content
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  2) async streaming                                                         #
# --------------------------------------------------------------------------- #
async def test_claude_tool_a_stream() -> None:
    event_store.clear_events()
    claude = ClaudeTool.builder().api_key(api_key).build()

    content = ""
    async for messages in claude.a_stream(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for msg in messages:
            assert msg.role == "assistant"
            if isinstance(msg.content, str):
                content += msg.content
                print(msg.content + "_", end="", flush=True)

    assert "Grafi" in content
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  3) synchronous one-shot                                                    #
# --------------------------------------------------------------------------- #
def test_claude_tool_execute() -> None:
    event_store.clear_events()
    claude = ClaudeTool.builder().api_key(api_key).build()

    messages = claude.execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )

    for msg in messages:
        assert msg.role == "assistant"
        assert msg.content and "Grafi" in msg.content
        print(msg.content)

    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  4) execute with custom chat params                                         #
# --------------------------------------------------------------------------- #
def test_claude_tool_with_chat_param() -> None:
    # Anthropic needs `max_tokens`; others are optional
    chat_param = {"temperature": 0.2}

    event_store.clear_events()
    claude = (
        ClaudeTool.builder()
        .api_key(api_key)
        .max_tokens(50)
        .chat_params(chat_param)
        .build()
    )

    messages = claude.execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )

    for msg in messages:
        assert msg.role == "assistant"
        assert msg.content and "Grafi" in msg.content
        print(msg.content)
        # 30 tokens ≈ < 250 chars for normal prose
        assert len(msg.content) < 250

    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  5) async one-shot                                                          #
# --------------------------------------------------------------------------- #
async def test_claude_tool_async() -> None:
    event_store.clear_events()
    claude = ClaudeTool.builder().api_key(api_key).build()

    content = ""
    async for messages in claude.a_execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for msg in messages:
            assert msg.role == "assistant"
            if isinstance(msg.content, str):
                content += msg.content

    print(content)
    assert "Grafi" in content
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  6) end-to-end pathway through LLMNode                                      #
# --------------------------------------------------------------------------- #
async def test_llm_a_stream_node_claude() -> None:
    event_store.clear_events()

    llm_stream_node = (
        LLMNode.builder()
        .command(
            LLMStreamResponseCommand.builder()
            .llm(ClaudeTool.builder().api_key(api_key).build())
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
        for msg in messages:
            assert msg.role == "assistant"
            if isinstance(msg.content, str):
                content += msg.content
                print(msg.content, end="", flush=True)

    assert "Grafi" in content
    # 2 events from ClaudeTool + 2 from LLMNode decorators
    assert len(event_store.get_events()) == 4


# --------------------------------------------------------------------------- #
#  Run directly                              #
# --------------------------------------------------------------------------- #

test_claude_tool_stream()
test_claude_tool_execute()
test_claude_tool_with_chat_param()

asyncio.run(test_claude_tool_a_stream())
asyncio.run(test_claude_tool_async())
asyncio.run(test_llm_a_stream_node_claude())
