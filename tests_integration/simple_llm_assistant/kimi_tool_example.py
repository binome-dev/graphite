"""
Kimi (Moonshot AI) Tool Example

This example demonstrates how to use the Kimi language model tool.
Kimi is provided by Moonshot AI (月之暗面).

API Key Configuration:
    To use this example, you need to obtain an API key from the Moonshot AI platform.
    
    Steps to get your API key:
    1. Visit the Moonshot AI console: https://platform.moonshot.cn/
    2. Sign up or log in to your account
    3. Navigate to the API Keys section
    4. Create a new API key or copy an existing one
    
    Set the API key as an environment variable:
        export MOONSHOT_API_KEY="your-api-key-here"
    
    Or set it directly in your environment before running this script.

Note: The API key is automatically read from the MOONSHOT_API_KEY environment variable.
If not set, the tool will use an empty string as default.
"""

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
from grafi.tools.llms.impl.kimi_tool import KimiTool
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

api_key = os.getenv("MOONSHOT_API_KEY", "")


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_kimi_tool_stream() -> None:
    await event_store.clear_events()
    kimi_tool = KimiTool.builder().is_streaming(True).api_key(api_key).build()
    content = ""
    async for messages in kimi_tool.invoke(
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


async def test_kimi_tool_with_chat_param() -> None:
    chat_param = {
        "temperature": 0.1,
        "max_tokens": 15,
    }
    kimi_tool = KimiTool.builder().api_key(api_key).chat_params(chat_param).build()
    await event_store.clear_events()
    async for messages in kimi_tool.invoke(
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


async def test_kimi_tool_with_structured_output() -> None:
    chat_param = {"response_format": UserForm}
    kimi_tool = KimiTool.builder().api_key(api_key).chat_params(chat_param).build()
    await event_store.clear_events()
    async for messages in kimi_tool.invoke(
        get_invoke_context(),
        [Message(role="user", content="Generate mock user with first name Grafi.")],
    ):
        for message in messages:
            assert message.role == "assistant"

            print(message.content)

            assert message.content is not None
            assert "Grafi" in message.content

    assert len(await event_store.get_events()) == 2


async def test_kimi_tool_async() -> None:
    kimi_tool = KimiTool.builder().api_key(api_key).build()
    await event_store.clear_events()

    content = ""
    async for messages in kimi_tool.invoke(
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
        .tool(KimiTool.builder().is_streaming(True).api_key(api_key).build())
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


async def test_kimi_tool_serialization() -> None:
    """Test serialization and deserialization of Kimi tool."""
    await event_store.clear_events()

    # Create original tool
    original_tool = KimiTool.builder().api_key(api_key).build()

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


async def test_kimi_tool_with_chat_param_serialization() -> None:
    """Test serialization with chat params."""
    await event_store.clear_events()

    chat_param = {
        "temperature": 0.1,
        "max_tokens": 15,
    }

    # Create original tool
    original_tool = (
        KimiTool.builder().api_key(api_key).chat_params(chat_param).build()
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


async def test_kimi_tool_structured_output_serialization() -> None:
    """Test serialization with structured output."""
    await event_store.clear_events()

    chat_param = {"response_format": UserForm}

    # Create original tool
    original_tool = (
        KimiTool.builder().api_key(api_key).chat_params(chat_param).build()
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


async def main():
    """
    Main function to run all tests sequentially with delays to avoid rate limiting.
    
    Note: Kimi API has a rate limit of 3 requests per minute (RPM) for free accounts.
    We add a 25-second delay between each test to stay within the limit.
    """
    # Run all tests sequentially with delays to respect rate limits
    # Kimi API limit: 3 requests per minute, so we wait 25 seconds between tests
    test_functions = [
        test_kimi_tool_with_chat_param,
        test_kimi_tool_with_structured_output,
        test_kimi_tool_stream,
        test_kimi_tool_async,
        test_llm_stream_node,
        test_kimi_tool_serialization,
        test_kimi_tool_with_chat_param_serialization,
        test_kimi_tool_structured_output_serialization,
    ]
    
    for i, test_func in enumerate(test_functions):
        print(f"\n{'='*60}")
        print(f"Running test {i+1}/{len(test_functions)}: {test_func.__name__}")
        print(f"{'='*60}\n")
        
        try:
            await test_func()
            print(f"✓ Test {test_func.__name__} completed successfully")
        except Exception as e:
            print(f"✗ Test {test_func.__name__} failed: {e}")
        
        # Add delay between tests (except after the last one)
        # 25 seconds ensures we stay within 3 RPM limit (60/3 = 20, add buffer)
        if i < len(test_functions) - 1:
            print("\nWaiting 25 seconds to avoid rate limiting...")
            await asyncio.sleep(25)


if __name__ == "__main__":
    asyncio.run(main())

