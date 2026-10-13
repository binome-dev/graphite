"""Transport failures expose no output and replay unacknowledged sibling input."""

import asyncio

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.exceptions import NodeExecutionError
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


class PairSource(EchoTool):
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.calls.append(["seed"])
        yield [Message(role="assistant", content="A1")]
        yield [Message(role="assistant", content="B1")]


async def main() -> None:
    for cancelled in (False, True):
        probe, source_tool, join_tool = ReadProbe(), PairSource(), EchoTool()
        a = Topic(name="a", event_queue=observed_queue(probe, "a"))
        b = Topic(name="b", event_queue=observed_queue(probe, "b"))
        source = Node(
            name="source",
            tool=source_tool,
            subscribed_expressions=[TopicExpr(topic=InputTopic(name="input"))],
            publisher_router=PublisherRouter(
                routes=[
                    PublishRoute(topic=a, when=route_a),
                    PublishRoute(topic=b, when=route_b),
                ]
            ),
        )
        join = make_node(
            "join",
            join_tool,
            SubscriptionBuilder().subscribed_to(a).and_().subscribed_to(b).build(),
            OutputTopic(name="output"),
        )
        workflow = EventDrivenWorkflow.builder().node(source).node(join).build()
        runtime, event = GrafiRuntime(), input_event()
        failure = RuntimeError("B transport failed")

        async def fail_b(topic: str, consumer: str) -> None:
            if topic == "b" and consumer == "join":
                await probe.wait_fetched("a", "join")
                if cancelled:
                    raise asyncio.CancelledError("transport interrupted")
                raise failure

        probe.before_fetch = fail_b
        async with asyncio.timeout(5):
            try:
                await drain(runtime, workflow, event)
            except NodeExecutionError as error:
                if cancelled:
                    assert isinstance(error.__cause__, RuntimeError)
                    assert "unexpectedly cancelled" in str(error.__cause__)
                else:
                    assert error.__cause__ is failure
            else:
                raise AssertionError("Transport failure ended as a success")
        assert join_tool.calls == []
        probe.assert_readers_closed()
        history = await runtime.services.event_store.get_agent_events(
            event.invoke_context.assistant_request_id
        )
        assert not any(
            isinstance(record, ConsumeFromTopicEvent) and record.consumer_name == "join"
            for record in history
        )
        probe.before_fetch = None
        async with asyncio.timeout(5):
            assert await drain(runtime, workflow, event) == ["A1|B1"]
        assert source_tool.calls == [["seed"]], "Recovery reran committed upstream work"
        assert join_tool.calls == [["A1", "B1"]]
        probe.assert_readers_closed()
        print(
            f"Failed read and same-request replay, transport cancellation={cancelled}: OK"
        )


if __name__ == "__main__":
    asyncio.run(main())
