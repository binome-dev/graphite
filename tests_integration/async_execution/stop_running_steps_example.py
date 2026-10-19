"""Stopping a running workflow ends its running steps before returning.

One source commits A1, so the AND join waits for b; another source is still
mid-stream when the workflow is stopped.
"""

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
from tests_integration.async_execution.support import assert_steps_ended
from tests_integration.async_execution.support import drain
from tests_integration.async_execution.support import input_event
from tests_integration.async_execution.support import make_node
from tests_integration.async_execution.support import until_stored


class WaitingSource(EchoTool):
    streaming: asyncio.Event = Field(default_factory=asyncio.Event, exclude=True)
    closed: asyncio.Event = Field(default_factory=asyncio.Event, exclude=True)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        try:
            yield [Message(role="assistant", content="A1")]
            await until_stored("a", "A1")  # The other source's A1 committed.
            self.streaming.set()
            await asyncio.Event().wait()
        finally:
            self.closed.set()


async def main() -> None:
    source_tool, join_tool = WaitingSource(), EchoTool()
    a, b = Topic(name="a"), Topic(name="b")
    first = make_node("first", EchoTool(), TopicExpr(topic=InputTopic(name="input")), a)
    source = make_node(
        "source", source_tool, TopicExpr(topic=InputTopic(name="input")), a
    )
    join = make_node(
        "join",
        join_tool,
        SubscriptionBuilder().subscribed_to(a).and_().subscribed_to(b).build(),
        OutputTopic(name="output"),
    )
    workflow = EventDrivenWorkflow.builder().node(first).node(source).node(join).build()
    task = asyncio.create_task(drain(GrafiRuntime(), workflow, input_event("A1")))
    try:
        async with asyncio.timeout(5):
            await source_tool.streaming.wait()  # The join is waiting for b.
            assert not task.done()
            workflow.stop()
            assert await task == []
        assert source_tool.closed.is_set()
        assert join_tool.calls == []
        assert_steps_ended("first", "source", "join")
    finally:
        workflow.stop()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    print("Workflow stop ends the active source and leaves the join waiting: OK")


if __name__ == "__main__":
    asyncio.run(main())
