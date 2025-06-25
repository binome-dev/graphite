import os
import uuid

from grafi.common.containers.container import container
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.duckduckgo_tool import DuckDuckGoTool
from tests_integration.function_call_assistant.simple_function_call_assistant import (
    SimpleFunctionCallAssistant,
)


event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_simple_function_call_assistant_with_duckduckgo() -> None:
    invoke_context = get_invoke_context()

    # Set up the assistant with DuckDuckGoTool
    assistant = (
        SimpleFunctionCallAssistant.builder()
        .name("DuckduckgoAssistant")
        .api_key(api_key)
        .function_tool(DuckDuckGoTool.builder().build())
        .build()
    )

    input_data = [Message(role="user", content="What are the current AI trends?")]

    # Invoke the assistant's function call
    output = assistant.invoke(invoke_context, input_data)
    print("Assistant output:", output)

    # Assert that the output is valid and check event count
    assert output is not None
    print(
        "Number of events recorded:",
        len(event_store.get_events()),
    )
    assert len(event_store.get_events()) == 24


test_simple_function_call_assistant_with_duckduckgo()
