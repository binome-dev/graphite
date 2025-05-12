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
from grafi.tools.llms.impl.deepseek_tool import DeepseekTool
from grafi.tools.llms.llm_stream_response_command import LLMStreamResponseCommand


event_store = container.event_store

# DeepSeek key comes from the same environment style you used for OpenAI
api_key = os.getenv("DEEPSEEK_API_KEY", "")


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


# --------------------------------------------------------------------------- #
#  synchronous streaming                                                      #
# --------------------------------------------------------------------------- #
def test_deepseek_tool_stream() -> None:
    event_store.clear_events()
    ds_tool = DeepseekTool.Builder().api_key(api_key).build()

    content = ""
    for messages in ds_tool.stream(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if message.content is not None:
                content += message.content
                print(message.content, end="", flush=True)

    assert content  # not empty
    assert "Grafi" in content
    # decorators record_tool_stream + record_tool_execution → 2 events
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  async streaming                                                            #
# --------------------------------------------------------------------------- #
async def test_deepseek_tool_a_stream() -> None:
    event_store.clear_events()
    ds_tool = DeepseekTool.Builder().api_key(api_key).build()

    content = ""
    async for messages in ds_tool.a_stream(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if message.content and isinstance(message.content, str):
                content += message.content
                print(message.content + "_", end="", flush=True)

    assert content
    assert "Grafi" in content
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  synchronous one-shot                                                       #
# --------------------------------------------------------------------------- #
def test_deepseek_tool_execute() -> None:
    event_store.clear_events()
    ds_tool = DeepseekTool.Builder().api_key(api_key).build()

    messages = ds_tool.execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )

    for message in messages:
        assert message.role == "assistant"
        assert message.content
        print(message.content)
        assert "Grafi" in message.content

    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  execute with custom chat params                                            #
# --------------------------------------------------------------------------- #
def test_deepseek_tool_with_chat_param() -> None:
    chat_param = {"temperature": 0.1, "max_tokens": 15}

    event_store.clear_events()
    ds_tool = DeepseekTool.Builder().api_key(api_key).chat_params(chat_param).build()

    messages = ds_tool.execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )

    for message in messages:
        assert message.role == "assistant"
        assert message.content
        print(message.content)
        assert "Grafi" in message.content
        assert len(message.content) < 70

    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  async one-shot                                                             #
# --------------------------------------------------------------------------- #
async def test_deepseek_tool_async() -> None:
    event_store.clear_events()
    ds_tool = DeepseekTool.Builder().api_key(api_key).build()

    content = ""
    async for messages in ds_tool.a_execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if message.content and isinstance(message.content, str):
                content += message.content

    print(content)
    assert "Grafi" in content
    assert len(event_store.get_events()) == 2


# --------------------------------------------------------------------------- #
#  end-to-end: LLMNode streaming with DeepseekTool                            #
# --------------------------------------------------------------------------- #
async def test_llm_a_stream_node_deepseek() -> None:
    event_store.clear_events()

    llm_stream_node = (
        LLMNode.Builder()
        .command(
            LLMStreamResponseCommand.Builder()
            .llm(DeepseekTool.Builder().api_key(api_key).build())
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
            if message.content and isinstance(message.content, str):
                content += message.content
                print(message.content, end="", flush=True)

    assert content
    assert "Grafi" in content
    # → 2 events from DeepseekTool + 2 from LLMNode wrapper
    assert len(event_store.get_events()) == 4


# synchronous tests
test_deepseek_tool_stream()
test_deepseek_tool_execute()
test_deepseek_tool_with_chat_param()

# async tests
asyncio.run(test_deepseek_tool_a_stream())
asyncio.run(test_deepseek_tool_async())
asyncio.run(test_llm_a_stream_node_deepseek())
