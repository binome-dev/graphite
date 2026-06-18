"""Asserting tests for event-replay recovery (the 'restorability' pillar).

These exercise EventDrivenWorkflow.init_workflow's recovery branch: when the
event store already has events for an assistant_request_id, the workflow restores
topic state and resumes instead of starting fresh.
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


class EchoTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    async def invoke(self, invoke_context, input_data):
        yield [Message(role="assistant", content="resumed response")]

    @classmethod
    async def from_dict(cls, data):  # pragma: no cover - not exercised here
        return cls(oi_span_type=OpenInferenceSpanKindValues.TOOL)


def _build_workflow() -> tuple[EventDrivenWorkflow, InputTopic, str]:
    input_topic = InputTopic(name="agent_input")
    output_topic = OutputTopic(name="agent_output")
    node = Node(
        name="echo_node",
        type="Node",
        tool=EchoTool(),
        subscribed_expressions=[TopicExpr(topic=input_topic)],
        publish_to=[output_topic],
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
async def test_count_pending_consumable_reflects_restored_work():
    """After restoring an unconsumed input, the pending count is non-zero."""
    workflow, _input_topic, _node_name = _build_workflow()
    request_id = "recovery-count"
    event = _pending_input_event(request_id)

    # Restore the topic state as init_workflow would.
    for topic in workflow._topics.values():
        await topic.reset()
    await workflow._topics["agent_input"].restore_topic(event)

    pending = await workflow._count_pending_consumable()
    assert pending == 1


@pytest.mark.asyncio
async def test_parallel_recovery_resumes_and_yields_output():
    """A resumed parallel run must drain restored work, not quiesce immediately.

    Regression test: before seeding the tracker on recovery, the parallel path
    declared quiescence before any node ran and yielded nothing.
    """
    workflow, _input_topic, _node_name = _build_workflow()
    request_id = "recovery-parallel"

    store = EventStoreInMemory()
    await store.record_event(_pending_input_event(request_id))

    fake_container = Mock()
    fake_container.event_store = store

    with patch("grafi.workflows.impl.event_driven_workflow.container", fake_container):
        outputs = []
        async for event in workflow.invoke(
            _pending_input_event(request_id), is_sequential=False
        ):
            outputs.append(event)

    assert outputs, "resumed parallel workflow yielded no output (immediate quiescence)"
    assert any(
        msg.content == "resumed response" for event in outputs for msg in event.data
    )


@pytest.mark.asyncio
async def test_sequential_recovery_resumes_and_yields_output():
    """The sequential path also resumes restored work and yields output."""
    workflow, _input_topic, _node_name = _build_workflow()
    request_id = "recovery-sequential"

    store = EventStoreInMemory()
    await store.record_event(_pending_input_event(request_id))

    fake_container = Mock()
    fake_container.event_store = store

    with patch("grafi.workflows.impl.event_driven_workflow.container", fake_container):
        outputs = []
        async for event in workflow.invoke(
            _pending_input_event(request_id), is_sequential=True
        ):
            outputs.append(event)

    assert outputs
    assert any(
        msg.content == "resumed response" for event in outputs for msg in event.data
    )
