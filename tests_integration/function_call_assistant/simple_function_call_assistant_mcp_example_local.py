import asyncio
import os
import uuid

from mcp import StdioServerParameters

from grafi.common.containers.container import container
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.mcp_tool import MCPTool
from tests_integration.function_call_assistant.simple_function_call_assistant import (
    SimpleFunctionCallAssistant,
)


# Known issue: running on windows may cause asyncio error, due to the way subprocesses are handled. This is a known issue with the mcp library.

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
        SimpleFunctionCallAssistant.builder()
        .name("MCPAssistant")
        .api_key(api_key)
        .function_tool(await MCPTool.builder().server_params(server_params).a_build())
        .build()
    )

    input_data = [
        Message(
            role="user", content="Please call mcp function 'echo' my name 'Graphite'?"
        )
    ]

    # Execute the assistant's function call
    async for output in assistant.a_execute(execution_context, input_data):
        print(output)
        assert output is not None

    assert len(event_store.get_events()) == 24


asyncio.run(test_simple_function_call_assistant_with_mcp())
