"""Integration test: concurrent invocations on ONE multi-node function-call assistant.

The hardest concurrency case: a single ``SimpleFunctionCallAssistant`` (a 3-node
workflow -- input LLM -> function call -> output LLM) is invoked several times at
once, each asking about a distinct postcode. Each response must reference its own
postcode and none of the others, proving the per-invocation isolation holds
across a multi-node, function-calling workflow (each run owns its own topic
queues, tracker, and stop flag).

Requires ``OPENAI_API_KEY`` (loaded from ``.env`` at the repo root).
"""

import asyncio
import os
import uuid

from dotenv import load_dotenv

from grafi.common.decorators.llm_function import llm_function
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import GrafiRuntime
from grafi.runtime.execution_services import bind_services
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from tests_integration.function_call_assistant.simple_function_call_assistant import (
    SimpleFunctionCallAssistant,
)

load_dotenv()

runtime = GrafiRuntime()
event_store = runtime.services.event_store
api_key = os.getenv("OPENAI_API_KEY", "")

# Distinct, non-overlapping postcodes so each answer is traceable to its request.
POSTCODES = ["11111", "22222", "33333"]


class WeatherMock(FunctionCallTool):
    @llm_function
    def get_weather_mock(self, postcode: str) -> str:
        """Return a weather report for the given postcode.

        Args:
            postcode (str): The postcode to report the weather for.

        Returns:
            str: A weather report mentioning the postcode.
        """
        return f"The weather of {postcode} is bad now."


def _invoke_context() -> InvokeContext:
    request_id = uuid.uuid4().hex
    return InvokeContext(
        conversation_id=request_id,
        invoke_id=request_id,
        assistant_request_id=request_id,
    )


async def _run_once(assistant: SimpleFunctionCallAssistant, postcode: str) -> str:
    contents = []
    event = PublishToTopicEvent(
        invoke_context=_invoke_context(),
        data=[Message(role="user", content=f"How's the weather in {postcode}?")],
    )
    async for out in assistant.invoke(event, is_sequential=False):
        for message in out.data:
            if isinstance(message.content, str):
                contents.append(message.content)
    return " ".join(contents)


async def test_concurrent_function_call_invokes_are_isolated() -> None:
    assert api_key, "OPENAI_API_KEY is not set (add it to .env at the repo root)"

    await event_store.clear_events()
    assistant = (
        SimpleFunctionCallAssistant.builder()
        .name("ConcurrentFunctionCallAssistant")
        .api_key(api_key)
        .function_tool(WeatherMock(name="WeatherMock"))
        .build()
    )

    results = await asyncio.gather(*[_run_once(assistant, p) for p in POSTCODES])

    for postcode, output in zip(POSTCODES, results):
        others = [p for p in POSTCODES if p != postcode]
        print(f"{postcode} -> {output!r}")
        assert (
            postcode in output
        ), f"response missing its postcode {postcode}: {output!r}"
        assert not any(
            other in output for other in others
        ), f"cross-talk in response for {postcode}: {output!r}"

    print("Concurrent function-call invocation isolation: OK")


with bind_services(runtime.services):
    asyncio.run(test_concurrent_function_call_invokes_are_isolated())
