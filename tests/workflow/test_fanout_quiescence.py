"""Characterization tests for fan-out delivery accounting (Defect #2).

The quiescence tracker counts outstanding *deliveries* (one per consumer of each
published event), not publications. Before the fix it counted publications, so a
single event fanned out to several subscribers was declared quiescent after only
the first subscriber committed -- silently dropping the rest of the work.
"""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.tools.tool import Tool
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class LabelTool(Tool):
    """Echoes a per-node label so each subscriber's output is distinguishable."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    label: str = "?"

    async def invoke(self, invoke_context, input_data):
        yield [Message(role="assistant", content=f"resp-{self.label}")]

    @classmethod
    async def from_dict(cls, data):  # pragma: no cover - not exercised here
        return cls(oi_span_type=OpenInferenceSpanKindValues.TOOL)


def _input_event(request_id: str) -> PublishToTopicEvent:
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


def _build_fanout_workflow() -> EventDrivenWorkflow:
    """One input topic feeding two independent subscribers, both publishing to
    the single output topic."""
    input_topic = InputTopic(name="agent_input")
    output_topic = OutputTopic(name="agent_output")
    node_a = Node(
        name="node_a",
        type="Node",
        tool=LabelTool(label="a"),
        subscribed_expressions=[TopicExpr(topic=input_topic)],
        publish_to=[output_topic],
    )
    node_b = Node(
        name="node_b",
        type="Node",
        tool=LabelTool(label="b"),
        subscribed_expressions=[TopicExpr(topic=input_topic)],
        publish_to=[output_topic],
    )
    return EventDrivenWorkflow.builder().node(node_a).node(node_b).build()


def test_topic_consumers_counts_every_subscriber():
    """The topology helper reports both subscribers of the fan-out input topic
    and the workflow itself as the consumer of the output topic."""
    workflow = _build_fanout_workflow()

    assert set(workflow._topic_consumers("agent_input")) == {"node_a", "node_b"}
    assert workflow._topic_consumers("agent_output") == [workflow.name]
    # Unknown topic -> no consumers (cannot hang execution).
    assert workflow._topic_consumers("does_not_exist") == []


@pytest.mark.asyncio
async def test_parallel_fanout_yields_every_subscriber_output():
    """Both subscribers must run: the workflow must not quiesce after only the
    first commits. Regression for the fan-out under-count."""
    workflow = _build_fanout_workflow()
    request_id = "fanout-parallel"

    fake_container = Mock()
    fake_container.event_store = EventStoreInMemory()

    with patch("grafi.workflows.impl.event_driven_workflow.container", fake_container):
        contents = [
            msg.content
            async for event in workflow.invoke(
                _input_event(request_id), is_sequential=False
            )
            for msg in event.data
        ]

    assert "resp-a" in contents
    assert "resp-b" in contents


@pytest.mark.asyncio
async def test_parallel_does_not_hang_on_unsatisfied_and_subscription():
    """A topic feeding a firing node AND a node whose AND-subscription can never
    be satisfied must still terminate (the parked delivery must not hang the
    run). Regression for the per-consumer accounting over-count."""
    import asyncio

    from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
    from grafi.topics.topic_impl.topic import Topic

    input_topic = InputTopic(name="agent_input")
    gate = Topic(name="gate_topic")  # nothing ever publishes here
    output_topic = OutputTopic(name="agent_output")

    firing = Node(
        name="firing",
        type="Node",
        tool=LabelTool(label="ok"),
        subscribed_expressions=[TopicExpr(topic=input_topic)],
        publish_to=[output_topic],
    )
    # Subscribes to (agent_input AND gate_topic); gate_topic never fires.
    stuck = Node(
        name="stuck",
        type="Node",
        tool=LabelTool(label="never"),
        subscribed_expressions=[
            SubscriptionBuilder()
            .subscribed_to(input_topic)
            .and_()
            .subscribed_to(gate)
            .build()
        ],
        publish_to=[output_topic],
    )
    workflow = EventDrivenWorkflow.builder().node(firing).node(stuck).build()

    fake_container = Mock()
    fake_container.event_store = EventStoreInMemory()

    with patch("grafi.workflows.impl.event_driven_workflow.container", fake_container):
        contents = []
        async with asyncio.timeout(10):  # fails loudly if it hangs
            async for event in workflow.invoke(
                _input_event("and-sub"), is_sequential=False
            ):
                contents.extend(msg.content for msg in event.data)

    # The firing node's output is produced; the stuck AND-node never fires.
    assert "resp-ok" in contents
    assert "resp-never" not in contents
