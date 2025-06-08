import asyncio
import os
import uuid

from pydantic import BaseModel

from grafi.common.containers.container import container
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm_stream_response_command import LLMStreamResponseCommand


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


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_openai_tool_stream() -> None:
    event_store.clear_events()
    openai_tool = OpenAITool.builder().api_key(api_key).build()
    content = ""
    for messages in openai_tool.stream(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if message.content is not None:
                content += message.content
                print(message.content, end="", flush=True)

    assert len(event_store.get_events()) == 2
    assert content is not None
    assert "Grafi" in content


async def test_openai_tool_a_stream() -> None:
    event_store.clear_events()
    openai_tool = OpenAITool.builder().api_key(api_key).build()
    content = ""
    async for messages in openai_tool.a_stream(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if message.content is not None and isinstance(message.content, str):
                content += message.content
                print(message.content + "_", end="", flush=True)

    assert len(event_store.get_events()) == 2
    assert content is not None
    assert "Grafi" in content


def test_openai_tool() -> None:
    openai_tool = OpenAITool.builder().api_key(api_key).build()
    event_store.clear_events()
    messages = openai_tool.execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )
    for message in messages:
        assert message.role == "assistant"

        print(message.content)

        assert len(event_store.get_events()) == 2
        assert message.content is not None
        assert "Grafi" in message.content


def test_openai_tool_with_chat_param() -> None:
    chat_param = {
        "temperature": 0.1,
        "max_tokens": 15,
    }
    openai_tool = OpenAITool.builder().api_key(api_key).chat_params(chat_param).build()
    event_store.clear_events()
    messages = openai_tool.execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    )
    for message in messages:
        assert message.role == "assistant"

        print(message.content)

        assert len(event_store.get_events()) == 2
        assert message.content is not None
        assert "Grafi" in message.content
        assert len(message.content) < 70


def test_openai_tool_with_structured_output() -> None:
    chat_param = {"response_format": UserForm}
    openai_tool = OpenAITool.builder().api_key(api_key).chat_params(chat_param).build()
    event_store.clear_events()
    messages = openai_tool.execute(
        get_execution_context(),
        [Message(role="user", content="Generate mock user with first name Grafi.")],
    )
    for message in messages:
        assert message.role == "assistant"

        print(message.content)

        assert len(event_store.get_events()) == 2
        assert message.content is not None
        assert "Grafi" in message.content


async def test_openai_tool_async() -> None:
    openai_tool = OpenAITool.builder().api_key(api_key).build()
    event_store.clear_events()

    content = ""
    async for messages in openai_tool.a_execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        for message in messages:
            assert message.role == "assistant"
            if message.content is not None and isinstance(message.content, str):
                content += message.content

    print(content)

    assert "Grafi" in content

    print(len(event_store.get_events()))

    assert len(event_store.get_events()) == 2


async def test_llm_a_stream_node() -> None:
    event_store.clear_events()
    llm_stream_node = (
        LLMNode.builder()
        .command(
            LLMStreamResponseCommand.builder()
            .llm(OpenAITool.builder().api_key(api_key).build())
            .build()
        )
        .build()
    )

    content = ""

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

    async for messages in llm_stream_node.a_execute(
        execution_context,
        [topic_event],
    ):
        for message in messages:
            assert message.role == "assistant"
            if message.content is not None and isinstance(message.content, str):
                content += message.content
                print(message.content, end="", flush=True)

    assert content is not None
    assert "Grafi" in content
    assert len(event_store.get_events()) == 4


test_openai_tool()
test_openai_tool_with_chat_param()
test_openai_tool_with_structured_output()
test_openai_tool_stream()
asyncio.run(test_openai_tool_a_stream())
asyncio.run(test_openai_tool_async())
asyncio.run(test_llm_a_stream_node())
