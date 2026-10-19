# We will test the SimpleLLMAssistant class in this file.

import asyncio
import os
import uuid

from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import Delta
from grafi.runtime import current_services
from tests_integration.simple_stream_assistant.simple_stream_assistant import (
    SimpleStreamAssistant,
)

event_store = current_services().event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_llm_assistant() -> None:
    assistant = (
        SimpleStreamAssistant.builder()
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
    await event_store.clear_events()

    content = ""
    streamed = ""

    async for item in assistant.invoke(
        PublishToTopicEvent(
            invoke_context=get_invoke_context(),
            data=[
                Message(
                    role="user", content="Hello, my name is Grafi, how are you doing?"
                )
            ],
        ),
        stream=True,
    ):
        if isinstance(item, Delta):  # The answer's text, as it comes.
            streamed += item.content
            print(item.content, end="", flush=True)
            continue
        for message in item.data:  # The answer, once stored.
            assert message.role == "assistant"
            content += str(message.content)

    print()
    assert "Grafi" in content
    assert streamed == content

    events = await event_store.get_events()
    print(f"Total events: {len(events)}")
    # 8 component events (invoke and respond for the assistant, the workflow,
    # the node and its tool), then a publication and its consumption for the
    # input and for the answer. Deltas are not stored.
    assert len(events) == 12

    # Save events to local json file
    # import json

    # events_data = [event.to_dict() for event in events]
    # with open("events.json", "w") as f:
    #     json.dump(events_data, f, indent=4)
    # print(f"Saved {len(events)} events to events.json")


asyncio.run(test_simple_llm_assistant())
