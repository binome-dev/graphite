import asyncio
import os
import uuid

from examples.simple_stream_assistant.simple_stream_function_call_assistant import (
    SimpleStreamFunctionCallAssistant,
)
from grafi.common.containers.container import container
from grafi.common.decorators.llm_function import llm_function
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.function_call_tool import FunctionCallTool


event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


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


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_function_call_assistant() -> None:
    event_store.clear_events()
    assistant = (
        SimpleStreamFunctionCallAssistant.Builder()
        .name("SimpleFunctionCallAssistant")
        .api_key(api_key)
        .function_tool(WeatherMock(name="WeatherMock"))
        .build()
    )

    # Test the run method
    input_data = [Message(role="user", content="Hello, how's the weather in 12345?")]

    content = ""

    async for messages in assistant.a_execute(
        get_execution_context(),
        input_data,
    ):
        for message in messages:
            assert message.role == "assistant"
            if message.content is not None:
                content += str(message.content)
                print(message.content, end="", flush=True)

    print(content)
    assert "bad" in content
    assert "12345" in content
    assert content is not None


asyncio.run(test_simple_function_call_assistant())
