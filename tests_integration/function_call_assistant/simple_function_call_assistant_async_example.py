import asyncio
import os
import uuid

from grafi.common.containers.container import container
from grafi.common.decorators.llm_function import llm_function
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from tests_integration.function_call_assistant.simple_function_call_assistant import (
    SimpleFunctionCallAssistant,
)


api_key = os.getenv("OPENAI_API_KEY", "")

event_store = container.event_store


class WeatherMock(FunctionCallTool):
    @llm_function
    async def get_weather_mock(self, postcode: str) -> str:
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


async def test_simple_function_call_assistant_async() -> None:
    invoke_context = get_invoke_context()

    assistant = (
        SimpleFunctionCallAssistant.builder()
        .name("SimpleFunctionCallAssistant")
        .api_key(api_key)
        .model("gpt-5-nano")
        .function_tool(WeatherMock(name="WeatherMock"))
        .build()
    )

    # Test the run method
    input_data = [Message(role="user", content="Hello, how's the weather in 12345?")]

    async for output in assistant.invoke(
        PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_data,
        )
    ):
        print(output)
        assert output is not None
        assert "12345" in str(output.data[0].content)
        assert "bad" in str(output.data[0].content)

    print(len(await event_store.get_events()))
    assert len(await event_store.get_events()) == 24

    # assistant.generate_workflow_graph()
    # assistant.generate_manifest()


asyncio.run(test_simple_function_call_assistant_async())
