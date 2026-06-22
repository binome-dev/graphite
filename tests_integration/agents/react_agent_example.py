import asyncio

from grafi.agents.react_agent import create_react_agent
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services


async def run_agent() -> None:
    react_agent = create_react_agent()

    output = await react_agent.run("What is agent framework called Graphite?")

    print(output)


# ReActAgent.run() calls the assistant's invoke under the hood, so it must run
# inside a bound runtime scope. ExecutionServices() supplies in-process defaults.
with bind_services(ExecutionServices()):
    asyncio.run(run_agent())
