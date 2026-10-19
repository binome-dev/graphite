"""A failed producer's output never reaches downstream nodes; retry completes it."""

import asyncio

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.runtime import GrafiRuntime
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from tests_integration.async_execution.support import EchoTool
from tests_integration.async_execution.support import drain
from tests_integration.async_execution.support import input_event
from tests_integration.async_execution.support import make_node


class FlakyStream(EchoTool):
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.calls.append(["call"])
        yield [Message(role="assistant", content="part-1", is_streaming=True)]
        if len(self.calls) == 1:
            raise RuntimeError("stream dropped")
        yield [Message(role="assistant", content="part-2", is_streaming=True)]


async def main() -> None:
    producer, sink = FlakyStream(), EchoTool()
    mid = Topic(name="mid")
    workflow = (
        EventDrivenWorkflow.builder()
        .node(
            make_node(
                "producer", producer, TopicExpr(topic=InputTopic(name="input")), mid
            )
        )
        .node(make_node("sink", sink, TopicExpr(topic=mid), OutputTopic(name="out")))
        .build()
    )
    runtime, event = GrafiRuntime(), input_event()
    async with asyncio.timeout(5):
        try:
            await drain(runtime, workflow, event)
        except NodeExecutionError as error:
            assert "stream dropped" in str(error)
        else:
            raise AssertionError("The failed producer ended as a success")
    # The sink never saw part-1 from the failed attempt, and the stored history
    # has nothing about mid that recovery would have to reject.
    assert sink.calls == []
    history = await runtime.services.event_store.get_agent_events(
        event.invoke_context.assistant_request_id
    )
    assert not any(
        isinstance(record, (PublishToTopicEvent, ConsumeFromTopicEvent))
        and record.name == "mid"
        for record in history
    )
    async with asyncio.timeout(5):
        assert await drain(runtime, workflow, event) == ["part-1|part-2"]
    assert len(producer.calls) == 2 and sink.calls == [["part-1", "part-2"]]
    print("Failed producer is invisible downstream; retry delivers the full step: OK")


if __name__ == "__main__":
    asyncio.run(main())
