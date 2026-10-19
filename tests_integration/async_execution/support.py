"""Deterministic tools and store observers for execution integrations."""

import asyncio
from uuid import uuid4

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.runtime import GrafiRuntime
from grafi.runtime.execution_services import current_services
from grafi.tools.tool import Tool
from grafi.topics.expressions.topic_expression import SubExpr
from grafi.topics.topic_base import TopicBase
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class EchoTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    calls: list[list[str]] = Field(default_factory=list)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        contents = []
        for message in input_data:
            assert isinstance(message.content, str)
            contents.append(message.content)
        self.calls.append(contents)
        yield [Message(role="assistant", content="|".join(contents))]


def make_node(name: str, tool: Tool, subscription: SubExpr, output: TopicBase) -> Node:
    return Node(
        name=name,
        tool=tool,
        subscribed_expressions=[subscription],
        publisher_router=PublisherRouter(routes=[PublishRoute(topic=output)]),
    )


def input_event(content: str = "hello") -> PublishToTopicEvent:
    request_id = uuid4().hex
    return PublishToTopicEvent(
        invoke_context=InvokeContext(
            conversation_id=request_id,
            invoke_id=request_id,
            assistant_request_id=request_id,
        ),
        data=[Message(role="user", content=content)],
    )


def route_a(event: PublishToTopicEvent) -> bool:
    return event.data[0].content in ("A1", "A2")


def route_b(event: PublishToTopicEvent) -> bool:
    return event.data[0].content == "B1"


async def drain(
    runtime: GrafiRuntime,
    workflow: EventDrivenWorkflow,
    event: PublishToTopicEvent,
    sequential: bool = False,
) -> list[str]:
    contents = []
    async for output in runtime.invoke(Assistant(workflow=workflow), event, sequential):
        for message in output.data:
            assert isinstance(message.content, str)
            contents.append(message.content)
    return contents


async def until_stored(topic: str, content: str) -> None:
    """Wait until the bound event store holds a publication of ``content`` on
    ``topic``, that is, until the step that published it has committed."""
    store = current_services().event_store
    while not any(
        isinstance(event, PublishToTopicEvent)
        and event.name == topic
        and event.data[0].content == content
        for event in await store.get_events()
    ):
        await asyncio.sleep(0.001)


def assert_steps_ended(*nodes: str) -> None:
    """Each step runs in a task named after its node; none may outlive a run."""
    left = [task for task in asyncio.all_tasks() if task.get_name() in nodes]
    assert not left, f"Steps survived the invocation: {left}"
