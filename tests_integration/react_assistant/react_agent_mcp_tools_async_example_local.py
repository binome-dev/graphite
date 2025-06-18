import asyncio

from mcp import StdioServerParameters

from grafi.agents.react_agent import create_agent
from grafi.tools.function_calls.impl.mcp_tool import MCPTool


async def run_agent() -> None:
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-everything"],
    )
    react_agent = create_agent(
        function_call_tool=await MCPTool.builder()
        .server_params(server_params)
        .a_build()
    )

    async for output in react_agent.a_run(
        "Please call mcp function 'echo' my name 'Graphite'?"
    ):
        print(output.content)


asyncio.run(run_agent())
