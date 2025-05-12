import asyncio
import json
import uuid

from examples.function_call_assistant.simple_ollama_function_call_assistant import (
    SimpleOllamaFunctionCallAssistant,
)
from grafi.common.containers.container import container
from grafi.common.decorators.llm_function import llm_function
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.functions.function_tool import FunctionTool


event_store = container.event_store


class WeatherMock(FunctionTool):
    @llm_function
    def get_weather(self, postcode: str) -> str:
        """
        Function to get weather information for a given postcode.

        Args:
            postcode (str): The postcode for which to retrieve weather information.

        Returns:
            str: A string containing a weather report for the given postcode.
        """
        return json.dumps(
            {
                "postcode": postcode,
                "weather": "Sunny",
            }
        )


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_function_call_assistant_async() -> None:
    execution_context = get_execution_context()
    assistant = (
        SimpleOllamaFunctionCallAssistant.Builder()
        .name("SimpleFunctionCallAssistant")
        .api_url("http://localhost:11434")
        .function_tool(WeatherMock(name="WeatherMock"))
        .model("qwen3")
        .build()
    )

    # Test the run method
    input_data = [Message(role="user", content="Hello, how's the weather in 12345?")]

    output = await assistant.a_execute(execution_context, input_data)
    print(output)
    assert output is not None
    print(len(event_store.get_events()))
    assert "12345" in output[0].content
    assert "sunny" in output[0].content
    assert len(event_store.get_events()) == 23


# Run the test function asynchronously
asyncio.run(test_simple_function_call_assistant_async())
