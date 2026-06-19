"""Invocation-isolation tests (Defect #3 / Phase 2).

Two concurrent invocations of the SAME assistant/workflow instance must not
share mutable runtime state. Before per-invocation isolation, each invocation
reset the shared topic queues and tracker, so concurrent requests erased each
other's state and could starve or cross-contaminate.
"""

import asyncio

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


class SlowEchoTool(Tool):
    """Yields a fixed response after a small delay, widening the window in which
    two concurrent invocations overlap."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    async def invoke(self, invoke_context, input_data):
        await asyncio.sleep(0.05)
        yield [Message(role="assistant", content="response")]

    @classmethod
    async def from_dict(cls, data):  # pragma: no cover - not exercised here
        return cls(oi_span_type=OpenInferenceSpanKindValues.TOOL)


def _build_workflow() -> EventDrivenWorkflow:
    input_topic = InputTopic(name="agent_input")
    output_topic = OutputTopic(name="agent_output")
    node = Node(
        name="echo_node",
        type="Node",
        tool=SlowEchoTool(),
        subscribed_expressions=[TopicExpr(topic=input_topic)],
        publish_to=[output_topic],
    )
    return EventDrivenWorkflow.builder().node(node).build()


def _input_event(request_id: str) -> PublishToTopicEvent:
    return PublishToTopicEvent(
        name="agent_input",
        type=TopicType.AGENT_INPUT_TOPIC_TYPE,
        publisher_name="EventDrivenWorkflow",
        publisher_type="EventDrivenWorkflow",
        offset=0,
        invoke_context=InvokeContext(
            conversation_id=request_id,
            invoke_id=request_id,
            assistant_request_id=request_id,
        ),
        data=[Message(role="user", content="hi")],
    )


@pytest.mark.asyncio
async def test_concurrent_invocations_are_isolated():
    """Two concurrent invocations of one workflow instance each complete with
    only their own request's events."""
    workflow = _build_workflow()
    store = EventStoreInMemory()

    from unittest.mock import Mock
    from unittest.mock import patch

    fake_container = Mock()
    fake_container.event_store = store

    async def run(request_id: str):
        outputs = []
        async with asyncio.timeout(5):
            async for event in workflow.invoke(
                _input_event(request_id), is_sequential=False
            ):
                outputs.append(event)
        return outputs

    with patch("grafi.workflows.impl.event_driven_workflow.container", fake_container):
        results_a, results_b = await asyncio.gather(run("alpha"), run("beta"))

    # Each invocation produced output...
    assert results_a, "invocation 'alpha' produced no output"
    assert results_b, "invocation 'beta' produced no output"

    # ...and saw only its own request_id (no cross-contamination).
    assert all(
        e.invoke_context.assistant_request_id == "alpha" for e in results_a
    ), "invocation 'alpha' saw another run's events"
    assert all(
        e.invoke_context.assistant_request_id == "beta" for e in results_b
    ), "invocation 'beta' saw another run's events"


@pytest.mark.asyncio
async def test_definition_holds_no_runtime_state_after_invoke():
    """A completed invocation leaves the workflow definition's shared topic
    queues empty, so a later invocation is unaffected by an earlier one."""
    workflow = _build_workflow()
    store = EventStoreInMemory()

    from unittest.mock import Mock
    from unittest.mock import patch

    fake_container = Mock()
    fake_container.event_store = store

    with patch("grafi.workflows.impl.event_driven_workflow.container", fake_container):
        async with asyncio.timeout(5):
            async for _ in workflow.invoke(_input_event("first"), is_sequential=False):
                pass

    # The definition's own topic queues were never used for execution.
    for topic in workflow._topics.values():
        assert not await topic.can_consume(workflow.name)
