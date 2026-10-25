"""Asserting tests for event-replay recovery (the 'restorability' pillar).

When the event store already has events for an assistant_request_id, a run
restores topic state from them and resumes instead of starting fresh.
"""

import json
from typing import Any
from typing import Dict
from typing import List

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.exceptions import WorkflowError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.tools.tool import Tool
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class EchoTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    async def invoke(self, invoke_context, input_data):
        return [Message(role="assistant", content="resumed response")]


def _build_workflow() -> tuple[EventDrivenWorkflow, InputTopic, str]:
    input_topic = InputTopic(name="agent_input")
    output_topic = OutputTopic(name="agent_output")
    node = Node(
        name="echo_node",
        type="Node",
        tool=EchoTool(),
        subscribed_expressions=[TopicExpr(topic=input_topic)],
        publisher_router=PublisherRouter(routes=[PublishRoute(topic=output_topic)]),
    )
    workflow = EventDrivenWorkflow.builder().node(node).build()
    return workflow, input_topic, node.name


def _pending_input_event(request_id: str) -> PublishToTopicEvent:
    """An input event that was published but not yet consumed before a crash."""
    return PublishToTopicEvent(
        name="agent_input",
        type=TopicType.AGENT_INPUT_TOPIC_TYPE,
        publisher_name="EventDrivenWorkflow",
        publisher_type="EventDrivenWorkflow",
        offset=0,
        invoke_context=InvokeContext(
            conversation_id="c",
            invoke_id="i",
            assistant_request_id=request_id,
        ),
        data=[Message(role="user", content="hello")],
    )


@pytest.mark.asyncio
async def test_parallel_recovery_resumes_and_yields_output(event_store):
    """A resumed parallel run must run the restored work, not end at once.

    Regression test: the old engine's quiescence tracker, not seeded on
    recovery, ended a resumed parallel run before any node ran.
    """
    workflow, _input_topic, _node_name = _build_workflow()
    request_id = "recovery-parallel"

    # Pre-seed the bound store so the workflow recovers instead of starting fresh.
    await event_store.record_event(_pending_input_event(request_id))

    outputs = []
    async for event in workflow.invoke(
        _pending_input_event(request_id), is_sequential=False
    ):
        outputs.append(event)

    assert outputs, "resumed parallel workflow yielded no output (ended at once)"
    assert any(
        msg.content == "resumed response" for event in outputs for msg in event.data
    )


@pytest.mark.asyncio
async def test_sequential_recovery_resumes_and_yields_output(event_store):
    """The sequential path also resumes restored work and yields output."""
    workflow, _input_topic, _node_name = _build_workflow()
    request_id = "recovery-sequential"

    await event_store.record_event(_pending_input_event(request_id))

    outputs = []
    async for event in workflow.invoke(
        _pending_input_event(request_id), is_sequential=True
    ):
        outputs.append(event)

    assert outputs
    assert any(
        msg.content == "resumed response" for event in outputs for msg in event.data
    )


class FlakyTool(Tool):
    """Fails its first call, as a step a crash or an outage cut short."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    calls: List[str] = Field(default_factory=list, exclude=True)

    async def invoke(self, invoke_context, input_data):
        self.calls.append(input_data[-1].content)
        if len(self.calls) == 1:
            raise RuntimeError("cut short")
        return [Message(role="assistant", content=f"done: {input_data[-1].content}")]


def _as_v1(event: Dict[str, Any]) -> Dict[str, Any]:
    """A topic event's JSON as grafi stored it before event version 2: its
    fields under ``event_context``, its messages as JSON text."""
    envelope = ("event_id", "event_type", "timestamp")
    return {
        **{key: event[key] for key in envelope},
        "event_version": "1.0",
        "event_context": {
            key: value
            for key, value in event.items()
            if key not in (*envelope, "event_version", "data")
        },
        "data": json.dumps(event["data"]),
    }


@pytest.mark.asyncio
async def test_a_request_stored_before_event_version_2_resumes(event_store):
    """A request interrupted under an earlier grafi resumes from its version 1
    events where it stopped: what was done is not done again."""
    first = Node(
        name="first",
        tool=EchoTool(),
        subscribed_expressions=[TopicExpr(topic=InputTopic(name="agent_input"))],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=Topic(name="mid"))]
        ),
    )
    flaky = FlakyTool()
    second = Node(
        name="second",
        tool=flaky,
        subscribed_expressions=[TopicExpr(topic=Topic(name="mid"))],
        publisher_router=PublisherRouter(
            routes=[PublishRoute(topic=OutputTopic(name="agent_output"))]
        ),
    )
    workflow = EventDrivenWorkflow.builder().node(first).node(second).build()
    request = _pending_input_event("recovery-v1")
    with pytest.raises(WorkflowError):
        [output async for output in workflow.invoke(request)]

    # The request's topic events, as version 1 stored them.
    stored = await event_store.get_agent_events("recovery-v1")
    topic_events = [event for event in stored if isinstance(event, TopicEvent)]
    assert {event.name for event in topic_events} == {"agent_input", "mid"}
    rows = [_as_v1(default_event_codec.encode(event)) for event in topic_events]
    await event_store.clear_events()
    await event_store.record_events([default_event_codec.decode(row) for row in rows])

    outputs = [output async for output in workflow.invoke(request)]

    assert [m.content for o in outputs for m in o.data] == ["done: resumed response"]
    assert flaky.calls == ["resumed response", "resumed response"]  # Not first.
