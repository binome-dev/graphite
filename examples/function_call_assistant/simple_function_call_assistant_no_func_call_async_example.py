import asyncio
import os
import uuid

from simple_function_call_assistant import SimpleFunctionCallAssistant

from grafi.common.containers.container import event_store
from grafi.common.decorators.llm_function import llm_function
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.functions.function_tool import FunctionTool

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


async def test_simple_function_call_assistant():
    execution_context = get_execution_context()
    assistant = (
        SimpleFunctionCallAssistant.Builder()
        .name("SimpleFunctionCallAssistant")
        .api_key(api_key)
        .function_tool(WeatherMock(name="mock_weather"))
        .build()
    )

    # Test the run method
    input_data = [Message(role="user", content="Hello, what is the aws EC2?")]

    if assistant.unfinished_requests:
        print(assistant.unfinished_requests)
        execution_context.assistant_request_id = assistant.unfinished_requests[0]

    output = await assistant.a_execute(execution_context, input_data)
    print(output)
    assert output is not None
    assert "EC2" in output[0].content
    print(len(event_store.get_events()))
    assert len(event_store.get_events()) == 11


asyncio.run(test_simple_function_call_assistant())
