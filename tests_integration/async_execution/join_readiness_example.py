"""Repeated A never satisfies A AND B; delayed B releases the complete batch.

Each publication comes from its own committed step: a step's publications become
visible to downstream nodes only when the step commits. A source waits until the
previous source's publication is stored, so the join sees A1 and A2 before B.
"""

import asyncio

from pydantic import Field

from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.runtime import ExecutionServices
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
from tests_integration.async_execution.support import route_a
from tests_integration.async_execution.support import route_b
from tests_integration.async_execution.support import until_stored


class GatedSource(EchoTool):
    """Emits one message once an earlier source's message on a is stored."""

    join: EchoTool = Field(exclude=True)
    content: str
    after: str | None = None

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        if self.after is not None:
            await until_stored("a", self.after)
            assert self.join.calls == [], "An AND join ran without B"
        yield [Message(role="assistant", content=self.content)]


async def main() -> None:
    # Each run gets a store of its own: until_stored scans the whole store.
    for send_b in (False, True):
        join = EchoTool()
        a, b = Topic(name="a"), Topic(name="b")
        routes = PublisherRouter(
            routes=[
                PublishRoute(topic=a, when=route_a),
                PublishRoute(topic=b, when=route_b),
            ]
        )
        sources = [
            Node(
                name=name,
                tool=GatedSource(join=join, content=content, after=after),
                subscribed_expressions=[TopicExpr(topic=InputTopic(name="input"))],
                publisher_router=routes,
            )
            for name, content, after in (
                ("first_a", "A1", None),
                ("second_a", "A2", "A1"),
                # Without B, the last source's message matches no route.
                ("late_b", "B1" if send_b else "unrouted", "A2"),
            )
        ]
        worker = make_node(
            "join",
            join,
            SubscriptionBuilder().subscribed_to(a).and_().subscribed_to(b).build(),
            OutputTopic(name="output"),
        )
        builder = EventDrivenWorkflow.builder()
        for source in sources:
            builder.node(source)
        workflow = builder.node(worker).build()
        async with asyncio.timeout(5):
            outputs = await drain(
                GrafiRuntime(ExecutionServices()), workflow, input_event()
            )
        assert outputs == (["A1|A2|B1"] if send_b else [])
        assert join.calls == ([["A1", "A2", "B1"]] if send_b else [])
        assert_steps_ended("first_a", "second_a", "late_b", "join")
        print(f"AND join, delayed B={send_b}: OK")

    tool = EchoTool()
    a, b = InputTopic(name="a"), Topic(name="b")
    worker = make_node(
        "join",
        tool,
        SubscriptionBuilder().subscribed_to(a).or_().subscribed_to(b).build(),
        OutputTopic(name="output"),
    )
    async with asyncio.timeout(5):
        outputs = await drain(
            GrafiRuntime(ExecutionServices()),
            EventDrivenWorkflow(nodes={worker.name: worker}),
            input_event("A1"),
        )
    assert outputs == ["A1"] and tool.calls == [["A1"]]
    assert_steps_ended("join")
    print("OR join with A only: OK")


if __name__ == "__main__":
    asyncio.run(main())
