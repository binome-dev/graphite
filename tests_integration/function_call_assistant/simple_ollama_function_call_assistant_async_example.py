import asyncio
import json
import uuid

from grafi.common.containers.container import container
from grafi.common.decorators.llm_function import llm_function
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from tests_integration.function_call_assistant.simple_ollama_function_call_assistant import (
    SimpleOllamaFunctionCallAssistant,
)


event_store = container.event_store


class WeatherMock(FunctionCallTool):
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


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_function_call_assistant_async() -> None:
    invoke_context = get_invoke_context()
    assistant = (
        SimpleOllamaFunctionCallAssistant.builder()
        .name("SimpleFunctionCallAssistant")
        .api_url("http://localhost:11434")
        .function_tool(WeatherMock(name="WeatherMock"))
        .model("qwen3")
        .build()
    )

    # Test the run method
    input_data = [Message(role="user", content="Hello, how's the weather in 12345?")]

    async for output in assistant.a_invoke(invoke_context, input_data):
        print(output)
        assert output is not None
        assert "12345" in str(output[0].content)
        assert "sunny" in str(output[0].content)

    print(len(event_store.get_events()))
    assert len(event_store.get_events()) == 27


# Run the test function asynchronously
asyncio.run(test_simple_function_call_assistant_async())
