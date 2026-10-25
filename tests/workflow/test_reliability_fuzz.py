"""Seeded fuzz of failures and early stops, checking event-sourcing invariants.

Each case runs one request against a small workflow with a fan-in topic (two
producers), an internal staged topic and an output, in both modes, the caller
streaming the tools' deltas.
Tools fail at random and the caller stops early at random; the request is then
resumed until it completes. After every attempt the stored history must have
contiguous topic positions and be accepted by recovery; across all attempts
every stored output must reach the caller at least once; and once the request
completes, resuming it delivers nothing more.
"""

import asyncio
import random
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.runtime import Delta
from grafi.runtime import emit_delta
from grafi.tools.tool import Tool
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_base import TopicBase
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.impl.workflow_run import WorkflowRun
from tests_integration.async_execution.support import input_event

MAX_ATTEMPTS = 12


class FlakyTool(Tool):
    """Streams a few pieces, then outputs them; fails partway on some
    attempts."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    chunks: int = 2
    failures_left: int = 0
    rng: Any = Field(default=None, exclude=True)

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> Messages:
        output: Messages = []
        for index in range(self.chunks):
            await asyncio.sleep(0)
            if self.failures_left and self.rng.random() < 0.5:
                self.failures_left -= 1
                raise RuntimeError(f"{self.name} failed")
            emit_delta(f"{self.name}-{index}")
            output.append(Message(role="assistant", content=f"{self.name}-{index}"))
        return output


def make_node(name: str, tool: Tool, source: TopicBase, destination: TopicBase) -> Node:
    return Node(
        name=name,
        tool=tool,
        subscribed_expressions=[TopicExpr(topic=source)],
        publisher_router=PublisherRouter(routes=[PublishRoute(topic=destination)]),
    )


def build_workflow(rng: random.Random) -> EventDrivenWorkflow:
    source, mid, out = (
        InputTopic(name="input"),
        Topic(name="mid"),
        OutputTopic(name="out"),
    )

    def tool(name: str) -> FlakyTool:
        return FlakyTool(name=name, failures_left=rng.randint(0, 2), rng=rng)

    return (
        EventDrivenWorkflow.builder()
        .node(make_node("a", tool("a"), source, mid))  # Fan-in on "mid" ...
        .node(make_node("c", tool("c"), source, mid))  # ... from two producers.
        .node(make_node("b", tool("b"), mid, out))
        .build()
    )


async def stored_publications(
    event_store: EventStore, request_id: str
) -> List[PublishToTopicEvent]:
    return [
        event
        for event in await event_store.get_agent_events(request_id)
        if isinstance(event, PublishToTopicEvent)
    ]


async def check_history(
    workflow: EventDrivenWorkflow,
    event_store: EventStore,
    event: PublishToTopicEvent,
) -> None:
    request_id = event.invoke_context.assistant_request_id
    publications = await stored_publications(event_store, request_id)
    positions: dict[str, List[int]] = {}
    for publication in publications:
        positions.setdefault(publication.name, []).append(publication.offset)
    for name, offsets in positions.items():
        assert sorted(offsets) == list(range(len(offsets))), (name, offsets)
    # Recovery accepts the history (it rejects gaps and conflicts).
    WorkflowRun(workflow, event_store)._restore(
        [
            e
            for e in await event_store.get_agent_events(request_id)
            if isinstance(e, TopicEvent)
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
@pytest.mark.parametrize("seed", range(25))
async def test_failures_and_early_stops_keep_history_consistent(
    event_store: EventStore, sequential: bool, seed: int
) -> None:
    rng = random.Random(seed)
    workflow = build_workflow(rng)
    event = input_event()
    request_id = event.invoke_context.assistant_request_id
    # Positions are reused when a step runs again, so each output is tracked
    # with the attempts that delivered it and the attempt that stored it.
    delivered: Dict[Tuple[str, int], List[int]] = {}
    stored_in: Dict[Tuple[str, int], int] = {}
    completed = False
    async with asyncio.timeout(20):
        for attempt in range(MAX_ATTEMPTS):
            stop_after = rng.choice([None, 0, 1, 2])
            outputs = workflow.invoke(event, sequential, stream=True)
            try:
                received = 0  # Outputs and deltas: a stop may land on either.
                async for output in outputs:
                    received += 1
                    if not isinstance(output, Delta):
                        delivered.setdefault((output.name, output.offset), []).append(
                            attempt
                        )
                    if stop_after is not None and received > stop_after:
                        break
                else:
                    completed = True
            except NodeExecutionError:
                pass
            finally:
                await outputs.aclose()
            await check_history(workflow, event_store, event)
            for publication in await stored_publications(event_store, request_id):
                if publication.name == "out":
                    stored_in.setdefault(
                        (publication.name, publication.offset), attempt
                    )
            if completed:
                break
    assert completed, "the request never completed"
    # Every stored output reached the caller, in or after the attempt that
    # stored it (an earlier attempt's delivery may have been of other work).
    for position, attempt in stored_in.items():
        assert any(a >= attempt for a in delivered.get(position, [])), position
    # Once complete, resuming the request delivers nothing more.
    async with asyncio.timeout(5):
        assert [output async for output in workflow.invoke(event, sequential)] == []
