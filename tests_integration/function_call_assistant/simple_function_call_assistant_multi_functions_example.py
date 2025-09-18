import asyncio
import os
import uuid

from grafi.common.containers.container import container
from grafi.common.decorators.llm_function import llm_function
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from tests_integration.function_call_assistant.simple_function_call_assistant import (
    SimpleFunctionCallAssistant,
)


event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


class LocalInfoMock(FunctionCallTool):
    @llm_function
    def get_weather_mock(self, postcode: str) -> str:
        """
        Function to get weather information for a given postcode.

        Args:
            postcode (str): The postcode for which to retrieve weather information.

        Returns:
            str: A string containing a weather report for the given postcode.
        """
        return f"The weather of {postcode} is bad now."

    @llm_function
    def get_population_mock(self, postcode: str) -> str:
        """
        Function to get population information for a given postcode.

        Args:
            postcode (str): The postcode for which to retrieve population information.

        Returns:
            int: An integer representing the population for the given postcode.
        """
        return "200000"


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_function_call_assistant() -> None:
    assistant = (
        SimpleFunctionCallAssistant.builder()
        .name("SimpleFunctionCallAssistant")
        .api_key(api_key)
        .function_tool(LocalInfoMock(name="LocalInfoMock"))
        .build()
    )

    # Test the run method
    input_data = [Message(role="user", content="Hello, how's the weather in 12345?")]

    output = await async_func_wrapper(
        assistant.a_invoke(
            PublishToTopicEvent(
                invoke_context=get_invoke_context(),
                data=input_data,
            ),
            is_sequential=True,
        )
    )
    print(output)
    assert output is not None
    assert "12345" in str(output[0].data[0].content)
    assert "bad" in str(output[0].data[0].content)
    print(len(await event_store.a_get_events()))
    assert len(await event_store.a_get_events()) == 24

    # Test restore from finished requests

    input_data = [
        Message(role="user", content="Hello, what's the population in 12345?")
    ]
    output = await async_func_wrapper(
        assistant.a_invoke(
            PublishToTopicEvent(
                invoke_context=get_invoke_context(),
                data=input_data,
            ),
            is_sequential=True,
        )
    )

    print(output)
    assert output is not None
    assert "12345" in str(output[0].data[0].content)
    assert "200,000" in str(output[0].data[0].content)
    print(len(await event_store.a_get_events()))
    assert len(await event_store.a_get_events()) == 48


asyncio.run(test_simple_function_call_assistant())
