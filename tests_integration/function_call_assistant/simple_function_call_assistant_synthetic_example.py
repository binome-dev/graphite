import asyncio
import os
import uuid
from datetime import datetime

from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic import Field

from grafi.common.containers.container import container
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.synthetic_tool import SyntheticTool
from tests_integration.function_call_assistant.simple_function_call_assistant import (
    SimpleFunctionCallAssistant,
)


load_dotenv()


class WeatherInput(BaseModel):
    """Input schema for weather forecast tool."""

    location: str = Field(
        ..., min_length=1, description="Location for weather forecast"
    )
    date_iso: str = Field(..., description="Date in ISO format (YYYY-MM-DD)")


class WeatherOutput(BaseModel):
    """Output schema for weather forecast tool."""

    forecast: str = Field(..., description="Weather forecast description")
    temperature_c: float = Field(..., description="Temperature in Celsius")
    chance_of_precip: float = Field(
        ..., ge=0, le=1, description="Chance of precipitation (0-1)"
    )


SYNTHETIC_WEATHER_SYSTEM_PROMPT = """You are a helpful weather assistant with access to a synthetic weather forecasting tool.

  ## Available Tool: synthetic_weather

  **Purpose:** Generate plausible weather forecasts for any location and date. This tool returns MODELED/SYNTHETIC data, not real weather information.

  **IMPORTANT:** You MUST call the synthetic_weather tool for ALL weather-related queries. Do NOT provide weather information from your training data.

  **Input Schema:**
  - `location` (string, required): The location for the weather forecast (e.g., "London", "New York", "Tokyo")
  - `date_iso` (string, required): The date in ISO format YYYY-MM-DD

  **Output Schema:**
  - `forecast` (string): A textual description of the weather conditions
  - `temperature_c` (float): Temperature in Celsius
  - `chance_of_precip` (float): Probability of precipitation (0-1)

  **Instructions:**
  1. ALWAYS call the synthetic_weather tool for weather queries - never answer from memory
  2. If the user doesn't specify a date, use today's date: {today}
  3. Extract the location from the user's query
  4. After receiving the tool response, present the information conversationally

  **Example:**
  User: "What's the weather in London today?"
  → You MUST call synthetic_weather(location="London", date_iso="{today}")
  """.format(
    today=datetime.now().strftime("%Y-%m-%d")
)

event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_function_call_assistant_with_synthetic_weather_tool() -> None:
    invoke_context = get_invoke_context()

    assistant = (
        SimpleFunctionCallAssistant.builder()
        .name("SyntheticToolAssistant")
        .api_key(api_key)
        .function_tool(
            SyntheticTool.builder()
            .tool_name("synthetic_weather")
            .description(
                "Returns a plausible weather forecast for a given date/location. This is MODELLED, not real data."
            )
            .input_model(WeatherInput)
            .output_model(WeatherOutput)
            .model("gpt-5-mini")
            .openai_api_key(api_key)
            .build()
        )
        .function_call_llm_system_message(SYNTHETIC_WEATHER_SYSTEM_PROMPT)
        .model("gpt-5-mini")
        .build()
    )

    input_data = [Message(role="user", content="What is the weather in London today?")]

    output = await async_func_wrapper(
        assistant.invoke(
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
        len(await event_store.get_events()),
    )
    assert len(await event_store.get_events()) == 24


asyncio.run(test_simple_function_call_assistant_with_synthetic_weather_tool())
