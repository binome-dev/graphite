import asyncio
import os
import uuid

from grafi.common.containers.container import container
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.mcp_connections import StreamableHttpConnection
from grafi.common.models.message import Message
from grafi.tools.function_calls.impl.mcp_tool import MCPTool
from tests_integration.function_call_assistant.simple_function_call_assistant import (
    SimpleFunctionCallAssistant,
)


# Known issue: running on windows may cause asyncio error, due to the way subprocesses are handled. This is a known issue with the mcp library.

event_store = container.event_store

api_key = os.getenv("OPENAI_API_KEY", "")


def get_invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


async def test_simple_function_call_assistant_with_mcp() -> None:
    invoke_context = get_invoke_context()

    server_params = {
        "hello": StreamableHttpConnection(
            {
                "url": "http://localhost:8000/mcp/",
                "transport": "http",
            }
        )
    }

    # Set up the assistant with TavilyTool
    assistant = (
        SimpleFunctionCallAssistant.builder()
        .name("MCPAssistant")
        .api_key(api_key)
        .function_tool(await MCPTool.builder().connections(server_params).a_build())
        .build()
    )

    input_data = [Message(role="user", content="Hi my name is Graphite.")]

    # Invoke the assistant's function call
    async for output in assistant.a_invoke(invoke_context, input_data):
        print(output)
        assert output is not None

    assert len(event_store.get_events()) == 24


asyncio.run(test_simple_function_call_assistant_with_mcp())
