"""Join inputs: a failed step's inputs are replayed; subscriptions are checked.

The AND/OR join readiness tests live in test_workflow_run.py.
"""

import asyncio

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.exceptions import WorkflowError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.tools.tool import Tool
from grafi.topics.expressions.topic_expression import CombinedExpr
from grafi.topics.expressions.topic_expression import LogicalOp
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class RecordingTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    calls: list[list[str]] = Field(default_factory=list)
    fail_first: bool = False

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.calls.append([str(message.content) for message in input_data])
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("join failed")
        yield [Message(role="assistant", content="joined")]


class PairTool(RecordingTool):
    """Publishes A1 and B1 in one step."""

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.calls.append([str(message.content) for message in input_data])
        yield [Message(role="assistant", content="A1")]
        yield [Message(role="assistant", content="B1")]


def join_node(tool: Tool, op: LogicalOp = LogicalOp.AND) -> Node:
    return Node(
        name="join",
        type="Node",
        tool=tool,
        subscribed_expressions=[
            CombinedExpr(
                op=op,
                left=TopicExpr(topic=InputTopic(name="a")),
                right=TopicExpr(topic=Topic(name="b")),
            )
        ],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=OutputTopic(name="output"))]
        ),
    )


def event(content: str) -> PublishToTopicEvent:
    return PublishToTopicEvent(
        name="a",
        publisher_name="test",
        publisher_type="test",
        invoke_context=InvokeContext(
            conversation_id="c", invoke_id="i", assistant_request_id="r"
        ),
        data=[Message(role="user", content=content)],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_inputs_of_a_failed_join_step_are_replayed(
    event_store: EventStore, sequential: bool
) -> None:
    a, b = Topic(name="a"), Topic(name="b")
    source_tool, join_tool = PairTool(), RecordingTool(fail_first=True)
    source = Node(
        name="source",
        tool=source_tool,
        subscribed_expressions=[TopicExpr(topic=InputTopic(name="input"))],
        publisher_router=PublisherRouter(
            routes=[
                PublishRoute(topic=a, when=lambda e: e.data[0].content == "A1"),
                PublishRoute(topic=b, when=lambda e: e.data[0].content == "B1"),
            ]
        ),
    )
    join = Node(
        name="join",
        tool=join_tool,
        subscribed_expressions=[
            CombinedExpr(
                op=LogicalOp.AND, left=TopicExpr(topic=a), right=TopicExpr(topic=b)
            )
        ],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=OutputTopic(name="output"))]
        ),
    )
    workflow = EventDrivenWorkflow.builder().node(source).node(join).build()
    input_event = event("seed")
    async with asyncio.timeout(5):
        with pytest.raises(NodeExecutionError, match="join failed"):
            async for _ in workflow.invoke(input_event, sequential):
                pass
    # The failed step took A1 and B1, but its consumptions were never stored.
    assert join_tool.calls == [["A1", "B1"]]
    assert not any(
        isinstance(record, ConsumeFromTopicEvent) and record.consumer_name == "join"
        for record in await event_store.get_agent_events("r")
    )
    async with asyncio.timeout(5):
        outputs = [
            message.content
            async for output in workflow.invoke(input_event, sequential)
            for message in output.data
        ]
    assert outputs == ["joined"]
    assert join_tool.calls == [["A1", "B1"], ["A1", "B1"]]
    assert len(source_tool.calls) == 1, "Recovery reran committed upstream work"


@pytest.mark.asyncio
@pytest.mark.parametrize("is_sequential", [False, True])
async def test_empty_subscriptions_rejected_before_input_is_saved(
    event_store: EventStore, is_sequential: bool
) -> None:
    node = join_node(RecordingTool(), LogicalOp.OR)
    empty = Node(name="empty", type="Node", tool=RecordingTool())
    with pytest.raises(WorkflowError, match="at least one subscription"):
        EventDrivenWorkflow.builder().node(node).node(empty).build()
    input_event = event("input")
    assert (
        await event_store.get_agent_events(
            input_event.invoke_context.assistant_request_id
        )
        == []
    )
    workflow = EventDrivenWorkflow.builder().node(node).build()
    async with asyncio.timeout(2):
        outputs = [
            message.content
            async for output in workflow.invoke(input_event, is_sequential)
            for message in output.data
        ]
    assert outputs == ["joined"]
