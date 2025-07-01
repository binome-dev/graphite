import asyncio

from grafi.agents.react_agent import create_react_agent
from grafi.common.models.mcp_connections import StdioConnection
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
        function_call_tool=await MCPTool.builder().connections(server_params).a_build()
    )

    async for output in react_agent.a_run(
        "Please call mcp function 'echo' my name 'Graphite'?"
    ):
        print(output.content)


asyncio.run(run_agent())
