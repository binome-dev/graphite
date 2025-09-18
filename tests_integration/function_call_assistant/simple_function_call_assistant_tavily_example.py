import asyncio
import os
import uuid

from grafi.common.containers.container import container
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.tavily_tool import TavilyTool
from tests_integration.function_call_assistant.simple_function_call_assistant import (
    SimpleFunctionCallAssistant,
)


event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")
tavily_api_key = os.getenv("TAVILY_API_KEY", "")


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_function_call_assistant_with_tavily() -> None:
    invoke_context = get_invoke_context()

    # Set up the assistant with TavilyTool
    assistant = (
        SimpleFunctionCallAssistant.builder()
        .name("TavilyAssistant")
        .api_key(api_key)
        .function_tool(
            TavilyTool.builder()
            .name("TavilyTestTool")
            .api_key(tavily_api_key)
            .max_tokens(6000)
            .search_depth("advanced")
            .build()
        )
        .build()
    )

    input_data = [Message(role="user", content="What are the current AI trends?")]

    # Invoke the assistant's function call
    output = await async_func_wrapper(
        assistant.a_invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=input_data,
            ),
            is_sequential=True,
        )
    )
    print("Assistant output:", output)

    # Assert that the output is valid and check event count
    assert output is not None
    print(
        "Number of events recorded:",
        len(await event_store.a_get_events()),
    )
    assert len(await event_store.a_get_events()) == 24


asyncio.run(test_simple_function_call_assistant_with_tavily())
