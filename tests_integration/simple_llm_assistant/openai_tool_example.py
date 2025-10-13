import asyncio
import os
import uuid

from pydantic import BaseModel

from grafi.common.containers.container import container
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.tool_factory import ToolFactory
from grafi.topics.topic_types import TopicType


class UserForm(BaseModel):
    """
    A simple user form model for demonstration purposes.
    """

    first_name: str
    last_name: str
    location: str
    gender: str


event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_openai_tool_stream() -> None:
    await event_store.clear_events()
    openai_tool = OpenAITool.builder().is_streaming(True).api_key(api_key).build()
    content = ""
    async for messages in openai_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if message.content is not None and isinstance(message.content, str):
                content += message.content
                print(message.content + "_", end="", flush=True)

    assert len(await event_store.get_events()) == 2
    assert content is not None
    assert "Grafi" in content


async def test_openai_tool_with_chat_param() -> None:
    chat_param = {
        "temperature": 0.1,
        "max_tokens": 15,
    }
    openai_tool = OpenAITool.builder().api_key(api_key).chat_params(chat_param).build()
    await event_store.clear_events()
    async for messages in openai_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"

            print(message.content)

            assert message.content is not None
            assert "Grafi" in message.content
            if isinstance(message.content, str):
                # Ensure the content length is within the expected range
                assert len(message.content) < 70

    assert len(await event_store.get_events()) == 2


async def test_openai_tool_with_structured_output() -> None:
    chat_param = {"response_format": UserForm}
    openai_tool = OpenAITool.builder().api_key(api_key).chat_params(chat_param).build()
    await event_store.clear_events()
    async for messages in openai_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Generate mock user with first name Grafi.")],
    ):
        for message in messages:
            assert message.role == "assistant"

            print(message.content)

            assert message.content is not None
            assert "Grafi" in message.content

    assert len(await event_store.get_events()) == 2


async def test_openai_tool_async() -> None:
    openai_tool = OpenAITool.builder().api_key(api_key).build()
    await event_store.clear_events()

    content = ""
    async for messages in openai_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if message.content is not None and isinstance(message.content, str):
                content += message.content

    print(content)

    assert "Grafi" in content

    print(len(await event_store.get_events()))

    assert len(await event_store.get_events()) == 2


async def test_llm_stream_node() -> None:
    await event_store.clear_events()
    llm_stream_node: Node = (
        Node.builder()
        .tool(OpenAITool.builder().is_streaming(True).api_key(api_key).build())
        .build()
    )

    content = ""

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

    async for event in llm_stream_node.invoke(
        invoke_context,
        [topic_event],
    ):
        for message in event.data:
            assert message.role == "assistant"
            if message.content is not None and isinstance(message.content, str):
                content += message.content
                print(message.content, end="", flush=True)

    assert content is not None
    assert "Grafi" in content
    assert len(await event_store.get_events()) == 4


async def test_openai_tool_serialization() -> None:
    """Test serialization and deserialization of OpenAI tool."""
    await event_store.clear_events()

    # Create original tool
    original_tool = OpenAITool.builder().api_key(api_key).build()

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
        for message in messages:
            assert message.role == "assistant"
            if message.content is not None and isinstance(message.content, str):
                content += message.content

    print(content)
    assert "Grafi" in content
    assert len(await event_store.get_events()) == 2


async def test_openai_tool_with_chat_param_serialization() -> None:
    """Test serialization with chat params."""
    await event_store.clear_events()

    chat_param = {
        "temperature": 0.1,
        "max_tokens": 15,
    }

    # Create original tool
    original_tool = (
        OpenAITool.builder().api_key(api_key).chat_params(chat_param).build()
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
        for message in messages:
            assert message.role == "assistant"
            print(message.content)
            assert message.content is not None
            assert "Grafi" in message.content
            if isinstance(message.content, str):
                assert len(message.content) < 70

    assert len(await event_store.get_events()) == 2


async def test_openai_tool_structured_output_serialization() -> None:
    """Test serialization with structured output."""
    await event_store.clear_events()

    chat_param = {"response_format": UserForm}

    # Create original tool
    original_tool = (
        OpenAITool.builder().api_key(api_key).chat_params(chat_param).build()
    )

    # Serialize to dict
    serialized = original_tool.to_dict()

    # Deserialize back
    restored_tool = await ToolFactory.from_dict(serialized)

    # Test that the restored tool works
    async for messages in restored_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Generate mock user with first name Grafi.")],
    ):
        for message in messages:
            assert message.role == "assistant"
            print(message.content)
            assert message.content is not None
            assert "Grafi" in message.content

    assert len(await event_store.get_events()) == 2


asyncio.run(test_openai_tool_with_chat_param())
asyncio.run(test_openai_tool_with_structured_output())
asyncio.run(test_openai_tool_stream())
asyncio.run(test_openai_tool_async())
asyncio.run(test_llm_stream_node())
asyncio.run(test_openai_tool_serialization())
asyncio.run(test_openai_tool_with_chat_param_serialization())
asyncio.run(test_openai_tool_structured_output_serialization())
