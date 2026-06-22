import asyncio

from grafi.agents.react_agent import create_react_agent
from grafi.common.models.mcp_connections import StdioConnection
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services
from grafi.tools.function_calls.impl.mcp_tool import MCPTool


async def run_agent() -> None:
    server_params = {
        "test": StdioConnection(
            **{
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-everything"],
                "transport": "stdio",
            }
        )
    }

    react_agent = create_react_agent(
        function_call_tool=await MCPTool.builder().connections(server_params).build()  # type: ignore
    )

    async for output in react_agent.run(
        "Please call mcp function 'echo' my name 'Graphite'?"
    ):
        print(output.content)


with bind_services(ExecutionServices()):
    asyncio.run(run_agent())
