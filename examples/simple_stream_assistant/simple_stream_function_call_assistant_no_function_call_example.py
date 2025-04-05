import asyncio
import os
import uuid

from simple_stream_function_call_assistant import SimpleStreamFunctionCallAssistant

from grafi.common.containers.container import container
from grafi.common.decorators.llm_function import llm_function
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.functions.function_tool import FunctionTool

event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY")


class WeatherMock(FunctionTool):
    @llm_function
    async def get_weather_mock(self, postcode: str):
        """
        Function to get weather information for a given postcode.

        Args:
            postcode (str): The postcode for which to retrieve weather information.

        Returns:
            str: A string containing a weather report for the given postcode.
        """
        return f"The weather of {postcode} is bad now."


def get_execution_context():
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_function_call_assistant_no_function_call():
    event_store.clear_events()
    assistant = (
        SimpleStreamFunctionCallAssistant.Builder()
        .name("SimpleFunctionCallAssistant")
        .api_key(api_key)
        .function_tool(WeatherMock(name="WeatherMock"))
        .build()
    )

    # Test the run method
    input_data = [Message(role="user", content="Hello, what's AWS EC2?")]

    content = ""

    async for message in assistant.a_execute(
        get_execution_context(),
        input_data,
    ):
        assert message.role == "assistant"
        if message.content is not None:
            content += message.content
            print(message.content, end="", flush=True)

    print(content)
    assert "EC2" in content
    assert content is not None


asyncio.run(test_simple_function_call_assistant_no_function_call())
