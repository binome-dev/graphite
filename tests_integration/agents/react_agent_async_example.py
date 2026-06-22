import asyncio

from grafi.agents.react_agent import create_react_agent
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services

react_agent = create_react_agent()


async def run_agent() -> None:
    async for output in react_agent.a_run("What is agent framework called Graphite?"):
        print(output)


# ReActAgent.a_run() calls the assistant's invoke under the hood, so it must run
# inside a bound runtime scope. ExecutionServices() supplies in-process defaults.
with bind_services(ExecutionServices()):
    asyncio.run(run_agent())
