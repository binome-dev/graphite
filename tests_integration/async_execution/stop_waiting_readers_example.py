"""Stopping a running workflow joins blocked readers before returning."""

import asyncio

from pydantic import Field

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.runtime import GrafiRuntime
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from tests_integration.async_execution.support import EchoTool
from tests_integration.async_execution.support import ReadProbe
from tests_integration.async_execution.support import drain
from tests_integration.async_execution.support import input_event
from tests_integration.async_execution.support import make_node
from tests_integration.async_execution.support import observed_queue


class WaitingSource(EchoTool):
    closed: asyncio.Event = Field(default_factory=asyncio.Event, exclude=True)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        try:
            yield [Message(role="assistant", content="A1")]
            await asyncio.Event().wait()
        finally:
            self.closed.set()


async def main() -> None:
    probe, source_tool, join_tool = ReadProbe(), WaitingSource(), EchoTool()
    a = Topic(name="a", event_queue=observed_queue(probe, "a"))
    b = Topic(name="b", event_queue=observed_queue(probe, "b"))
    source = make_node(
        "source", source_tool, TopicExpr(topic=InputTopic(name="input")), a
    )
    join = make_node(
        "join",
        join_tool,
        SubscriptionBuilder().subscribed_to(a).and_().subscribed_to(b).build(),
        OutputTopic(name="output", event_queue=observed_queue(probe, "output")),
    )
    workflow = EventDrivenWorkflow.builder().node(source).node(join).build()
    task = asyncio.create_task(drain(GrafiRuntime(), workflow, input_event()))
    try:
        async with asyncio.timeout(5):
            await probe.wait_started("b", "join", 2)
            assert not task.done()
            workflow.stop()
            assert await task == []
        assert source_tool.closed.is_set()
        assert join_tool.calls == []
        assert ("b", "join") in probe.cancelled
        probe.assert_readers_closed()
    finally:
        workflow.stop()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    print("Workflow stop closes blocked readers and the active source: OK")


if __name__ == "__main__":
    asyncio.run(main())
