import asyncio

from grafi.agents.react_agent import create_react_agent


async def run_agent() -> None:
    react_agent = create_react_agent()

    output = await react_agent.run("What is agent framework called Graphite?")

    print(output)


asyncio.run(run_agent())
