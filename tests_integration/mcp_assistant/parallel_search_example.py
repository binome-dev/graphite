"""Run keyless web search through a Graphite workflow and a remote MCP server."""

import argparse
import asyncio
import json
import uuid

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.runtime.runtime import GrafiRuntime
from grafi.tools.functions.impl.mcp_function_tool import MCPFunctionTool
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

PARALLEL_MCP_CONFIG = {
    "mcpServers": {
        "parallel": {
            "transport": "http",
            "url": "https://search.parallel.ai/mcp",
            "headers": {"User-Agent": "graphite-parallel-search-example"},
        }
    }
}


async def search(objective: str, queries: list[str]) -> list[str]:
    """Return source excerpts using the standalone MCP function workflow path."""
    tool = await MCPFunctionTool.initialize(
        name="ParallelSearch",
        mcp_config=PARALLEL_MCP_CONFIG,
        function_name="web_search",
    )
    input_topic = InputTopic(name="search_input")
    output_topic = OutputTopic(name="search_output")
    node = (
        Node.builder()
        .name("ParallelSearchNode")
        .subscribe(input_topic)
        .tool(tool)
        .publish_to(output_topic)
        .build()
    )
    workflow = EventDrivenWorkflow.builder().name("search").node(node).build()
    assistant = Assistant(name="SearchAssistant", workflow=workflow)
    session_id = uuid.uuid4().hex
    event = PublishToTopicEvent(
        invoke_context=InvokeContext(
            conversation_id=session_id,
            invoke_id=uuid.uuid4().hex,
            assistant_request_id=uuid.uuid4().hex,
        ),
        data=[
            Message(
                role="user",
                content=json.dumps(
                    {
                        "objective": objective,
                        "search_queries": queries,
                        "session_id": session_id,
                    }
                ),
            )
        ],
    )
    results = []
    async for output in GrafiRuntime().invoke(assistant, event):
        for message in output.data:
            if isinstance(message.content, str):
                results.append(message.content)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("objective", help="Information to find on the web")
    parser.add_argument(
        "--query",
        action="append",
        required=True,
        help="Search keywords; repeat for multiple queries",
    )
    args = parser.parse_args()
    for result in asyncio.run(search(args.objective, args.query)):
        print(result)


if __name__ == "__main__":
    main()
