import os
import uuid

from simple_function_call_assistant import SimpleFunctionCallAssistant
from tools.tavily_tool import TavilyTool

from grafi.common.containers.container import event_store
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message

api_key = os.getenv("OPENAI_API_KEY")
tavily_api_key = os.getenv("TAVILY_API_KEY")


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def test_simple_function_call_assistant_with_tavily():
    execution_context = get_execution_context()

    # Set up the assistant with TavilyTool
    assistant = (
        SimpleFunctionCallAssistant.Builder()
        .name("TavilyAssistant")
        .api_key(api_key)
        .function_tool(
            TavilyTool.Builder()
            .name("TavilyTestTool")
            .api_key(tavily_api_key)
            .max_tokens(6000)
            .search_depth("advanced")
            .build()
        )
        .build()
    )

    input_data = [Message(role="user", content="What are the current AI trends?")]

    if assistant.unfinished_requests:
        print("Unfinished requests:", assistant.unfinished_requests)
        execution_context.assistant_request_id = assistant.unfinished_requests[0]

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


test_simple_function_call_assistant_with_tavily()
