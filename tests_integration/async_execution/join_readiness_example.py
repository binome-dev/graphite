"""Repeated A never satisfies A AND B; delayed B releases the complete batch."""

import asyncio

from pydantic import Field

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
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
from tests_integration.async_execution.support import route_a
from tests_integration.async_execution.support import route_b


class StaggeredSource(EchoTool):
    probe: ReadProbe = Field(exclude=True)
    join: EchoTool = Field(exclude=True)
    send_b: bool

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        yield [Message(role="assistant", content="A1")]
        await self.probe.wait_started("b", "join", 2)
        yield [Message(role="assistant", content="A2")]
        await self.probe.wait_started("b", "join", 3)
        assert self.join.calls == [], "An AND join ran without B"
        if self.send_b:
            yield [Message(role="assistant", content="B1")]


async def main() -> None:
    for send_b in (False, True):
        probe, join = ReadProbe(), EchoTool()
        a = Topic(name="a", event_queue=observed_queue(probe, "a"))
        b = Topic(name="b", event_queue=observed_queue(probe, "b"))
        source = Node(
            name="source",
            tool=StaggeredSource(probe=probe, join=join, send_b=send_b),
            subscribed_expressions=[TopicExpr(topic=InputTopic(name="input"))],
            publisher_router=PublisherRouter(
                routes=[
                    PublishRoute(topic=a, when=route_a),
                    PublishRoute(topic=b, when=route_b),
                ]
            ),
        )
        worker = make_node(
            "join",
            join,
            SubscriptionBuilder().subscribed_to(a).and_().subscribed_to(b).build(),
            OutputTopic(name="output"),
        )
        workflow = EventDrivenWorkflow.builder().node(source).node(worker).build()
        async with asyncio.timeout(5):
            outputs = await drain(GrafiRuntime(), workflow, input_event())
        assert outputs == (["A1|A2|B1"] if send_b else [])
        assert join.calls == ([["A1", "A2", "B1"]] if send_b else [])
        assert ("b", "join") in probe.cancelled
        probe.assert_readers_closed()
        print(f"AND join, delayed B={send_b}: OK")

    probe, tool = ReadProbe(), EchoTool()
    a = InputTopic(name="a", event_queue=observed_queue(probe, "a"))
    b = Topic(name="b", event_queue=observed_queue(probe, "b"))
    worker = make_node(
        "join",
        tool,
        SubscriptionBuilder().subscribed_to(a).or_().subscribed_to(b).build(),
        OutputTopic(name="output"),
    )
    async with asyncio.timeout(5):
        outputs = await drain(
            GrafiRuntime(),
            EventDrivenWorkflow(nodes={worker.name: worker}),
            input_event("A1"),
        )
    assert outputs == ["A1"] and tool.calls == [["A1"]]
    probe.assert_readers_closed()
    print("OR join with A only: OK")


if __name__ == "__main__":
    asyncio.run(main())
