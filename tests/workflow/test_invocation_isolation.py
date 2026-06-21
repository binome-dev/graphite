"""Concurrent-invocation isolation (the 'one assistant, many invokes' goal).

Characterization test for Defect #3 / runtime Gap 00: two ``invoke()`` calls on
the *same* workflow instance, in flight at the same time, must complete
independently. Each run owns its own runtime state (topic queues, tracker, ready
queue, stop flag); they share only the immutable definition.

Before per-invocation isolation this FAILS: the two runs share one tracker and
one set of topic queues, and ``init_workflow`` resets them, so the second invoke
drains/resets the first mid-flight (one run yields nothing, or the run hangs).
"""

import asyncio
from unittest.mock import Mock

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
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class MarkerTool(Tool):
    """Yields a marker derived from the invoke context, after a small await.

    The marker lets a run's output be traced back to the request that produced
    it; the ``sleep`` forces the two concurrent runs to interleave so any shared
    runtime state corrupts deterministically.
    """

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    async def invoke(self, invoke_context, input_data):
        await asyncio.sleep(0.05)
        yield [
            Message(role="assistant", content=f"out:{invoke_context.conversation_id}")
        ]

    @classmethod
    async def from_dict(cls, data):  # pragma: no cover - not exercised here
        return cls(oi_span_type=OpenInferenceSpanKindValues.TOOL)


def _build_workflow() -> EventDrivenWorkflow:
    input_topic = InputTopic(name="agent_input")
    output_topic = OutputTopic(name="agent_output")
    node = Node(
        name="marker_node",
        type="Node",
        tool=MarkerTool(),
        subscribed_expressions=[TopicExpr(topic=input_topic)],
        publish_to=[output_topic],
    )
    return EventDrivenWorkflow.builder().node(node).build()


def _input(marker: str) -> PublishToTopicEvent:
    return PublishToTopicEvent(
        invoke_context=InvokeContext(
            conversation_id=marker,
            invoke_id=f"invoke-{marker}",
            assistant_request_id=f"req-{marker}",
        ),
        data=[Message(role="user", content=f"hello {marker}")],
    )


async def _drain(
    workflow: EventDrivenWorkflow, event: PublishToTopicEvent, sequential: bool
):
    return [out async for out in workflow.invoke(event, is_sequential=sequential)]


@pytest.mark.asyncio
@pytest.mark.parametrize("sequential", [False, True])
async def test_concurrent_invokes_on_one_instance_are_isolated(sequential, monkeypatch):
    """Two concurrent invokes on one workflow instance complete independently."""
    workflow = _build_workflow()

    # A shared store is fine: events are partitioned by assistant_request_id.
    store = EventStoreInMemory()
    fake_container = Mock()
    fake_container.event_store = store
    monkeypatch.setattr(
        "grafi.workflows.impl.event_driven_workflow.container", fake_container
    )

    results_a, results_b = await asyncio.wait_for(
        asyncio.gather(
            _drain(workflow, _input("alpha"), sequential),
            _drain(workflow, _input("beta"), sequential),
        ),
        timeout=10,
    )

    # Each run yields exactly its own output -- no drops, no cross-talk.
    assert [m.content for e in results_a for m in e.data] == ["out:alpha"]
    assert [m.content for e in results_b for m in e.data] == ["out:beta"]


@pytest.mark.asyncio
async def test_stop_does_not_leak_across_concurrent_invokes(monkeypatch):
    """Stopping is scoped: one run finishing/stopping must not halt another.

    Here both runs simply complete; the assertion is that running them
    concurrently does not strand either one (a shared stop flag / tracker would).
    """
    workflow = _build_workflow()
    store = EventStoreInMemory()
    fake_container = Mock()
    fake_container.event_store = store
    monkeypatch.setattr(
        "grafi.workflows.impl.event_driven_workflow.container", fake_container
    )

    batches = await asyncio.wait_for(
        asyncio.gather(*[_drain(workflow, _input(f"r{i}"), False) for i in range(4)]),
        timeout=10,
    )

    for i, batch in enumerate(batches):
        assert [m.content for e in batch for m in e.data] == [f"out:r{i}"]
