"""Deterministic tools and observable real queues for execution integrations."""

import asyncio
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Optional
from uuid import uuid4

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.runtime import GrafiRuntime
from grafi.tools.tool import Tool
from grafi.topics.expressions.topic_expression import SubExpr
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue
from grafi.topics.topic_base import TopicBase
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class ReadProbe:
    def __init__(self) -> None:
        self.tasks: set[asyncio.Task[Any]] = set()
        self.rounds: dict[tuple[str, str], int] = {}
        self.started: dict[tuple[str, str, int], asyncio.Event] = {}
        self.fetched: dict[tuple[str, str], asyncio.Event] = {}
        self.cancelled: set[tuple[str, str]] = set()
        self.before_fetch: Optional[Callable[[str, str], Awaitable[None]]] = None

    async def wait_started(self, topic: str, consumer: str, round: int) -> None:
        await self.started.setdefault((topic, consumer, round), asyncio.Event()).wait()

    async def wait_fetched(self, topic: str, consumer: str) -> None:
        await self.fetched.setdefault((topic, consumer), asyncio.Event()).wait()

    def assert_readers_closed(self) -> None:
        assert self.tasks, "The scenario must exercise queue readers"
        assert all(task.done() for task in self.tasks), "Reader survived invocation"


def observed_queue(probe: ReadProbe, topic: str) -> InMemTopicEventQueue:
    # Each definition gets a queue class capturing only this scenario's probe.
    # WorkflowRun creates fresh instances via type(queue)(), retaining the hooks
    # without sharing queue records or modifying framework methods globally.
    class ObservedQueue(InMemTopicEventQueue):
        async def fetch(
            self,
            consumer_id: str,
            offset: Optional[int] = None,
            timeout: Optional[float] = None,
        ) -> list[TopicEvent]:
            task = asyncio.current_task()
            assert task is not None
            probe.tasks.add(task)
            key = (topic, consumer_id)
            round = probe.rounds.get(key, 0) + 1
            probe.rounds[key] = round
            probe.started.setdefault((*key, round), asyncio.Event()).set()
            try:
                if probe.before_fetch is not None:
                    await probe.before_fetch(topic, consumer_id)
                records = await super().fetch(consumer_id, offset, timeout)
                if records:
                    probe.fetched.setdefault(key, asyncio.Event()).set()
                return records
            except asyncio.CancelledError:
                probe.cancelled.add(key)
                raise

    return ObservedQueue()


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
