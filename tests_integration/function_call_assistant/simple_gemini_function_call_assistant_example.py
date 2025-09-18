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
from tests_integration.function_call_assistant.simple_gemini_function_call_assistant import (
    SimpleGeminiFunctionCallAssistant,
)


event_store = container.event_store

api_key = os.getenv("GEMINI_API_KEY", "")


class WeatherMock(FunctionCallTool):
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


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_function_call_assistant() -> None:
    invoke_context = get_invoke_context()

    assistant = (
        SimpleGeminiFunctionCallAssistant.builder()
        .name("SimpleGeminiFunctionCallAssistant")
        .api_key(api_key)
        .function_tool(WeatherMock(name="WeatherMock"))
        .build()
    )

    # Test the run method
    input_data = [Message(role="user", content="Hello, how's the weather in 12345?")]

    output = await async_func_wrapper(
        assistant.a_invoke(
            PublishToTopicEvent(
                invoke_context=invoke_context,
                data=input_data,
            ),
            is_sequential=True,
        )
    )
    print(output)
    assert output is not None
    assert "weather" in str(output[0].data[0].content)
    print(len(await event_store.a_get_events()))
    assert len(await event_store.a_get_events()) == 24


asyncio.run(test_simple_function_call_assistant())
