import os
import uuid

from simple_function_call_assistant import SimpleFunctionCallAssistant
from tools.duckduckgo_tool import DuckDuckGoTool

from grafi.common.containers.container import container
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message

event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY")


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_simple_function_call_assistant_with_duckduckgo():
    execution_context = get_execution_context()

    # Set up the assistant with DuckDuckGoTool
    assistant = (
        SimpleFunctionCallAssistant.Builder()
        .name("DuckduckgoAssistant")
        .api_key(api_key)
        .function_tool(DuckDuckGoTool.Builder().build())
        .build()
    )

    input_data = [Message(role="user", content="What are the current AI trends?")]

    # Execute the assistant's function call
    output = assistant.execute(execution_context, input_data)
    print("Assistant output:", output)

    # Assert that the output is valid and check event count
    assert output is not None
    print(
        "Number of events recorded:",
        len(event_store.get_events()),
    )
    assert len(event_store.get_events()) == 23


test_simple_function_call_assistant_with_duckduckgo()
