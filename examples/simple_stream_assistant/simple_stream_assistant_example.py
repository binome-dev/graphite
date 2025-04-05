# We will test the SimpleLLMAssistant class in this file.

import asyncio
import os
import uuid

from simple_stream_assistant import SimpleStreamAssistant

from grafi.common.containers.container import container
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message

event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY")


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_llm_assistant():
    assistant = (
        SimpleStreamAssistant.Builder()
        .name("SimpleStreamAssistant")
        .system_message(
            """You're a friendly and helpful assistant, always eager to make tasks easier and provide clear, supportive answers. 
                You respond warmly to questions, and always call the user's name, making users feel comfortable and understood. 
                If you don't have all the information, you reassure users that you're here to help them find the best answer or solution. 
                Your tone is approachable and optimistic, and you aim to make each interaction enjoyable."""
        )
        .api_key(api_key)
        .build()
    )
    event_store.clear_events()

    content = ""

    async for message in assistant.a_execute(
        get_execution_context(),
        [Message(role="user", content="Hello, my name is Grafi, how are you doing?")],
    ):
        assert message.role == "assistant"
        if message.content is not None:
            content += message.content
            print(message.content, end="", flush=True)

    print(content)
    assert "Grafi" in content
    assert content is not None

    events = event_store.get_events()
    print(len(events))
    assert len(events) == 11


asyncio.run(test_simple_llm_assistant())
