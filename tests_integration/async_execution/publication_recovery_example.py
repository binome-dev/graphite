"""Fan-out keeps each publication's position and resumes at the next one; a
step failing mid-stream stores nothing and streams again when retried."""

import asyncio
import json
from uuid import uuid4

from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.runtime import Delta
from grafi.runtime import GrafiRuntime
from grafi.runtime import emit_delta
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from tests_integration.async_execution.support import EchoTool
from tests_integration.async_execution.support import drain
from tests_integration.async_execution.support import input_event


class StreamTool(EchoTool):
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.calls.append(["seed"])
        for text in ("one", "two", "three"):
            yield [Message(role="assistant", content=text)]


class InterruptedStreamTool(EchoTool):
    partial_received: asyncio.Event = Field(default_factory=asyncio.Event, exclude=True)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.calls.append(["seed"])
        for text in ("one", "two", "three"):
            emit_delta(text)
            if len(self.calls) == 1 and text == "two":
                await self.partial_received.wait()
                raise RuntimeError("stream interrupted")
        yield [Message(role="assistant", content="one two three")]


async def check_recovery(sequential: bool) -> None:
    a, b = OutputTopic(name="a"), OutputTopic(name="b")
    tool = StreamTool()
    source = Node(
        name="source",
        tool=tool,
        subscribed_expressions=[TopicExpr(topic=InputTopic(name="input"))],
        publisher_router=PublisherRouter(
            routes=[
                PublishRoute(topic=a),
                PublishRoute(topic=b),
                PublishRoute(topic=a),
            ]
        ),
    )
    workflow = EventDrivenWorkflow.builder().node(source).build()
    runtime, event = GrafiRuntime(), input_event()
    async with asyncio.timeout(5):
        assert sorted(await drain(runtime, workflow, event, sequential)) == sorted(
            ["one", "two", "three"] * 2
        )
    store = runtime.services.event_store
    history = await store.get_agent_events(event.invoke_context.assistant_request_id)
    outputs = [
        record
        for record in history
        if isinstance(record, PublishToTopicEvent) and record.name in ("a", "b")
    ]
    assert len(outputs) == len({record.event_id for record in outputs}) == 6
    for name in ("a", "b"):
        published = [record for record in outputs if record.name == name]
        assert [record.offset for record in published] == [0, 1, 2]
        consumed = [
            record
            for record in history
            if isinstance(record, ConsumeFromTopicEvent)
            and record.name == name
            and record.consumer_name == workflow.name
        ]
        assert [record.offset for record in consumed] == [0, 1, 2]
    for offset in range(3):
        pair = [record for record in outputs if record.offset == offset]
        assert pair[0].emission_id == pair[1].emission_id
        stored = json.loads(json.dumps(default_event_codec.encode(pair[0])))
        assert default_event_codec.decode(stored) == pair[0]

    # Simulate later, persisted outputs still awaiting delivery. Restore from a
    # deliberately reordered history to exercise the recorded topic positions.
    tail = input_event("later")
    publications = [
        tail.model_copy(
            update={
                "event_id": uuid4().hex,
                "emission_id": tail.event_id,
                "name": topic.name,
                "type": topic.type,
                "offset": 3,
                "invoke_context": event.invoke_context,
            }
        )
        for topic in (a, b)
    ]
    await store.clear_events()
    await store.record_events([*publications, *reversed(history)])
    async with asyncio.timeout(5):
        assert await drain(runtime, workflow, event, sequential) == ["later", "later"]
    assert tool.calls == [["seed"]], "Recovery reran a committed source node"
    print(f"Fan-out offsets and same-request recovery, sequential={sequential}: OK")


async def main() -> None:
    await check_recovery(sequential=False)
    await check_recovery(sequential=True)
    await check_interrupted_stream_retry()


async def check_interrupted_stream_retry() -> None:
    tool = InterruptedStreamTool()
    node = Node(
        name="source",
        tool=tool,
        subscribed_expressions=[TopicExpr(topic=InputTopic(name="input"))],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=OutputTopic(name="out"))]
        ),
    )
    workflow = EventDrivenWorkflow.builder().node(node).build()
    runtime, event = GrafiRuntime(), input_event()
    partial = []
    async with asyncio.timeout(5):
        try:
            async for item in runtime.invoke(
                Assistant(workflow=workflow), event, stream=True
            ):
                assert isinstance(item, Delta)  # No output is stored yet.
                partial.append(item.content)
                if item.content == "two":
                    tool.partial_received.set()
        except NodeExecutionError as error:
            assert "stream interrupted" in str(error)
        else:
            raise AssertionError("Interrupted stream ended as a success")
    assert partial == ["one", "two"]
    history = await runtime.services.event_store.get_agent_events(
        event.invoke_context.assistant_request_id
    )
    assert not any(
        isinstance(record, TopicEvent) and record.name == "out" for record in history
    ), "The failed step stored nothing; its deltas are never stored"
    async with asyncio.timeout(5):
        assert await drain(runtime, workflow, event) == ["one two three"]
    assert len(tool.calls) == 2
    print("Mid-stream failure stores nothing; the retry, same request ID, does: OK")


if __name__ == "__main__":
    asyncio.run(main())
