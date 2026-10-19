"""A failed join exposes no output and replays the inputs it took on resume.

The join takes A1 and B1 together. Its step fails (or its tool raises
CancelledError on its own, as a transport's timeout may), so neither input is
recorded as consumed: resuming the same request runs the join again on both,
without rerunning the source that committed them.
"""

import asyncio

from pydantic import Field

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
from tests_integration.async_execution.support import assert_steps_ended
from tests_integration.async_execution.support import drain
from tests_integration.async_execution.support import input_event
from tests_integration.async_execution.support import make_node
from tests_integration.async_execution.support import route_a
from tests_integration.async_execution.support import route_b


class PairSource(EchoTool):
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.calls.append(["seed"])
        yield [Message(role="assistant", content="A1")]
        yield [Message(role="assistant", content="B1")]


class FailingJoin(EchoTool):
    """Fails its first call with ``failure``."""

    failure: BaseException = Field(exclude=True)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        if not self.calls:
            self.calls.append([str(message.content) for message in input_data])
            raise self.failure
        async for messages in super().invoke(invoke_context, input_data):
            yield messages


async def main() -> None:
    for cancelled in (False, True):
        failure: BaseException = (
            asyncio.CancelledError("transport interrupted")
            if cancelled
            else RuntimeError("B transport failed")
        )
        source_tool, join_tool = PairSource(), FailingJoin(failure=failure)
        a, b = Topic(name="a"), Topic(name="b")
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
        async with asyncio.timeout(5):
            try:
                await drain(runtime, workflow, event)
            except NodeExecutionError as error:
                if cancelled:
                    assert isinstance(error.__cause__, RuntimeError)
                    assert "unexpectedly cancelled" in str(error.__cause__)
                    assert error.__cause__.__cause__ is failure
                else:
                    assert error.__cause__ is failure
            else:
                raise AssertionError("The join's failure ended as a success")
        assert join_tool.calls == [["A1", "B1"]]
        assert_steps_ended("source", "join")
        history = await runtime.services.event_store.get_agent_events(
            event.invoke_context.assistant_request_id
        )
        assert not any(
            isinstance(record, ConsumeFromTopicEvent) and record.consumer_name == "join"
            for record in history
        )
        async with asyncio.timeout(5):
            assert await drain(runtime, workflow, event) == ["A1|B1"]
        assert source_tool.calls == [["seed"]], "Recovery reran committed upstream work"
        assert join_tool.calls == [["A1", "B1"], ["A1", "B1"]]
        assert_steps_ended("source", "join")
        print(f"Failed join and same-request replay, tool cancellation={cancelled}: OK")


if __name__ == "__main__":
    asyncio.run(main())
