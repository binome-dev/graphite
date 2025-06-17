# We will test the SimpleLLMAssistant class in this file.

import asyncio
import json
import os
import uuid

from examples.simple_llm_assistant.simple_multi_llm_assistant import (
    SimpleMultiLLMAssistant,
)
from grafi.common.containers.container import container
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages


event_store = container.event_store


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def openai_function(input_data: Messages) -> str:
    # Simulate a function call to OpenAI's API
    # In a real-world scenario, this would involve making an API request
    # and returning the response.
    last_message = input_data[-1].content

    return json.dumps({"model": "openai", "content": last_message})


def deepseek_function(input_data: Messages) -> str:
    # Simulate a function call to DeepSeek's API
    # In a real-world scenario, this would involve making an API request
    # and returning the response.
    last_message = input_data[-1].content

    return json.dumps({"model": "deepseek", "content": last_message})


def gemini_function(input_data: Messages) -> str:
    # Simulate a function call to Gemini's API
    # In a real-world scenario, this would involve making an API request
    # and returning the response.
    last_message = input_data[-1].content

    return json.dumps({"model": "gemini", "content": last_message})


def qwen_function(input_data: Messages) -> str:
    # Simulate a function call to Qwen's API
    # In a real-world scenario, this would involve making an API request
    # and returning the response.
    last_message = input_data[-1].content

    return json.dumps({"model": "qwen", "content": last_message})


def human_request_process_function(input_data: Messages) -> str:
    # Simulate a function call to Qwen's API
    # In a real-world scenario, this would involve making an API request
    # and returning the response.
    last_message = input_data[-1].content

    return last_message


async def test_simple_multi_llm_assistant_async() -> None:
    execution_context = get_execution_context()

    assistant = SimpleMultiLLMAssistant(
        name="SimpleMultiLLMAssistant",
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openai_function=openai_function,
        deepseek_function=deepseek_function,
        gemini_function=gemini_function,
        qwen_function=qwen_function,
        human_request_process_function=human_request_process_function,
    )

    event_store.clear_events()

    input_data = [
        Message(
            content="Hello, my name is Grafi, I felt stressful today. Can you help me address my stress by saying my name? It is important to me.",
            role="user",
        )
    ]
    async for output in assistant.a_execute(execution_context, input_data):
        print(output)
        assert output is not None
    print(len(event_store.get_events()))
    assert len(event_store.get_events()) == 57


asyncio.run(test_simple_multi_llm_assistant_async())
