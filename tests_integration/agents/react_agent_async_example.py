import asyncio

from grafi.agents.react_agent import create_react_agent


react_agent = create_react_agent()


async def run_agent() -> None:
    async for output in react_agent.a_run("What is agent framework called Graphite?"):
        print(output)


asyncio.run(run_agent())
