import asyncio
import json
import os
import uuid

from mcp import StdioServerParameters

from examples.function_call_assistant.simple_function_call_assistant import (
    SimpleFunctionCallAssistant,
)
from grafi.common.containers.container import container
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.functions.impl.mcp_tool import MCPTool


### Known issue: running on windows may cause asyncio error, due to the way subprocesses are handled. This is a known issue with the mcp library.

event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def get_execution_context() -> ExecutionContext:
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_function_call_assistant_with_mcp() -> None:
    execution_context = get_execution_context()

    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-everything"],
    )

    # Set up the assistant with TavilyTool
    assistant = (
        SimpleFunctionCallAssistant.Builder()
        .name("MCPAssistant")
        .api_key(api_key)
        .function_tool(await MCPTool.Builder().server_params(server_params).a_build())
        .build()
    )

    input_data = [
        Message(
            role="user", content="Please call mcp function 'echo' my name 'Graphite'?"
        )
    ]

    # Execute the assistant's function call
    output = await assistant.a_execute(execution_context, input_data)
    print("Assistant output:", output)

    events = []
    for event in event_store.get_events():
        events.append(event.to_dict())

    string = json.dumps(events, indent=4)
    # print(string)
    # Assert that the output is valid and check event count
    assert output is not None
    print(
        "Number of events recorded:",
        len(event_store.get_events()),
    )
    assert len(event_store.get_events()) == 21


asyncio.run(test_simple_function_call_assistant_with_mcp())
