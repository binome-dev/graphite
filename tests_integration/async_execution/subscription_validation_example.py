"""Rejected definitions persist nothing; corrected definitions reuse the request."""

import asyncio

from grafi.common.exceptions import WorkflowError
from grafi.nodes.node import Node
from grafi.runtime import GrafiRuntime
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from tests_integration.async_execution.support import EchoTool
from tests_integration.async_execution.support import drain
from tests_integration.async_execution.support import input_event
from tests_integration.async_execution.support import make_node


async def main() -> None:
    for sequential in (False, True):
        runtime, tool = GrafiRuntime(), EchoTool()
        event = input_event()
        node = make_node(
            "echo",
            tool,
            TopicExpr(topic=InputTopic(name="input")),
            OutputTopic(name="output"),
        )
        invalid_tool = EchoTool()
        try:
            EventDrivenWorkflow.builder().node(node).node(
                Node(name="invalid", tool=invalid_tool)
            ).build()
        except WorkflowError as error:
            assert "at least one subscription" in str(error)
        else:
            raise AssertionError("An empty subscription was accepted")
        assert (
            await runtime.services.event_store.get_agent_events(
                event.invoke_context.assistant_request_id
            )
            == []
        )
        assert invalid_tool.calls == []
        corrected = EventDrivenWorkflow.builder().node(node).build()
        async with asyncio.timeout(5):
            assert await drain(runtime, corrected, event, sequential) == ["hello"]
        assert tool.calls == [["hello"]]
        print(
            f"Build validation and same-request invocation, sequential={sequential}: OK"
        )


if __name__ == "__main__":
    asyncio.run(main())
