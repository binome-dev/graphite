"""Unit tests for WorkflowRun and its engine/recovery helpers.

These exercise the per-invocation runtime object directly (no LLM): the
isolation invariants that make concurrent invocation safe, the topology /
commit / progress helpers shared by both engines, error wrapping in ``run``,
stop-forwarding from the definition, and the seeding/recovery in ``init``.
"""

import uuid

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import NodeExecutionError
from grafi.common.exceptions import WorkflowError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.tools.tool import Tool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.queue_impl.in_mem_topic_event_queue import InMemTopicEventQueue
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from grafi.workflows.impl.workflow_run import WorkflowRun


class EchoTool(Tool):
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    async def invoke(self, invoke_context, input_data):
        yield [Message(role="assistant", content="ok")]

    @classmethod
    async def from_dict(cls, data):  # pragma: no cover - not exercised here
        return cls(oi_span_type=OpenInferenceSpanKindValues.TOOL)


class BoomTool(Tool):
    """A tool whose invocation always raises (an async generator that raises)."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL

    async def invoke(self, invoke_context, input_data):
        raise RuntimeError("boom")
        yield  # pragma: no cover - unreachable; makes this an async generator

    @classmethod
    async def from_dict(cls, data):  # pragma: no cover - not exercised here
        return cls(oi_span_type=OpenInferenceSpanKindValues.TOOL)


def _ctx() -> InvokeContext:
    request_id = uuid.uuid4().hex
    return InvokeContext(
        conversation_id=request_id,
        invoke_id=request_id,
        assistant_request_id=request_id,
    )


def _pub(content: str = "hi", name: str = "") -> PublishToTopicEvent:
    return PublishToTopicEvent(
        name=name,
        invoke_context=_ctx(),
        data=[Message(role="user", content=content)],
    )


def _workflow(tool: Tool = None) -> EventDrivenWorkflow:
    """input(agent_input) -> node -> output(agent_output)."""
    input_topic = InputTopic(name="agent_input")
    output_topic = OutputTopic(name="agent_output")
    node = Node(
        name="node",
        type="Node",
        tool=tool or EchoTool(),
        subscribed_expressions=[TopicExpr(topic=input_topic)],
        publish_to=[output_topic],
    )
    return EventDrivenWorkflow.builder().node(node).build()


def _and_workflow() -> EventDrivenWorkflow:
    """A node subscribing to (agent_input AND gate); gate is a plain Topic."""
    input_topic = InputTopic(name="agent_input")
    gate = Topic(name="gate")
    output_topic = OutputTopic(name="agent_output")
    node = Node(
        name="stuck",
        type="Node",
        tool=EchoTool(),
        subscribed_expressions=[
            SubscriptionBuilder()
            .subscribed_to(input_topic)
            .and_()
            .subscribed_to(gate)
            .build()
        ],
        publish_to=[output_topic],
    )
    return EventDrivenWorkflow.builder().node(node).build()


# --------------------------------------------------------------------------- #
# Construction / isolation invariants
# --------------------------------------------------------------------------- #


class TestWorkflowRunConstruction:
    def test_per_run_topics_are_independent_copies(self):
        wf = _workflow()
        run1 = WorkflowRun(wf, EventStoreInMemory())
        run2 = WorkflowRun(wf, EventStoreInMemory())

        # Distinct topic objects, distinct from the definition and each other.
        assert run1.topics["agent_input"] is not wf._topics["agent_input"]
        assert run1.topics["agent_input"] is not run2.topics["agent_input"]
        # And distinct queue instances (the isolated runtime state).
        assert (
            run1.topics["agent_input"].event_queue
            is not run2.topics["agent_input"].event_queue
        )
        assert (
            run1.topics["agent_input"].event_queue
            is not wf._topics["agent_input"].event_queue
        )

    def test_queue_kind_is_preserved(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        assert isinstance(run.topics["agent_input"].event_queue, InMemTopicEventQueue)

    def test_runs_have_independent_runtime_state(self):
        wf = _workflow()
        r1 = WorkflowRun(wf, EventStoreInMemory())
        r2 = WorkflowRun(wf, EventStoreInMemory())
        assert r1.tracker is not r2.tracker
        assert r1.invoke_queue is not r2.invoke_queue
        r1._stop_requested = True
        assert r2._stop_requested is False

    @pytest.mark.asyncio
    async def test_publishing_to_one_run_does_not_affect_another(self):
        wf = _workflow()
        r1 = WorkflowRun(wf, EventStoreInMemory())
        r2 = WorkflowRun(wf, EventStoreInMemory())

        await r1.topics["agent_input"].publish_data(_pub())

        assert await r1.topics["agent_input"].can_consume("node")
        assert not await r2.topics["agent_input"].can_consume("node")


# --------------------------------------------------------------------------- #
# Control
# --------------------------------------------------------------------------- #


class TestWorkflowRunStop:
    def test_stop_sets_flag_and_force_stops_tracker(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        assert not run._stop_requested
        assert not run.tracker._force_stopped

        run.stop()

        assert run._stop_requested
        assert run.tracker._force_stopped


# --------------------------------------------------------------------------- #
# Topology / quiescence helpers
# --------------------------------------------------------------------------- #


class TestNodeCanInvoke:
    @pytest.mark.asyncio
    async def test_and_subscription_requires_all_topics(self):
        wf = _and_workflow()
        run = WorkflowRun(wf, EventStoreInMemory())
        node = run.nodes["stuck"]

        assert not await run._node_can_invoke(node)  # nothing published

        await run.topics["agent_input"].publish_data(_pub())
        assert not await run._node_can_invoke(node)  # only one branch satisfied

        await run.topics["gate"].publish_data(_pub("go"))
        assert await run._node_can_invoke(node)  # both branches satisfied


class TestAddToInvokeQueue:
    @pytest.mark.asyncio
    async def test_adds_ready_subscriber(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        event = await run.topics["agent_input"].publish_data(_pub())
        await run._add_to_invoke_queue(event)
        assert run.nodes["node"] in run.invoke_queue

    @pytest.mark.asyncio
    async def test_unknown_topic_is_noop(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        await run._add_to_invoke_queue(_pub(name="does_not_exist"))
        assert len(run.invoke_queue) == 0


class TestCommitEvents:
    def _consume_event(self) -> ConsumeFromTopicEvent:
        return ConsumeFromTopicEvent(
            name="agent_input",
            type=TopicType.AGENT_INPUT_TOPIC_TYPE,
            consumer_name="node",
            consumer_type="Node",
            offset=0,
            invoke_context=_ctx(),
            data=[Message(role="user", content="x")],
        )

    @pytest.mark.asyncio
    async def test_commit_releases_tracked_deliveries(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        await run.tracker.on_messages_published(1)
        assert not await run.tracker.is_quiescent()

        await run._commit_events("node", [self._consume_event()], track_commit=True)
        assert await run.tracker.is_quiescent()

    @pytest.mark.asyncio
    async def test_commit_skips_tracker_when_disabled(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        await run.tracker.on_messages_published(1)

        await run._commit_events("node", [self._consume_event()], track_commit=False)
        assert not await run.tracker.is_quiescent()  # still 1 uncommitted

    @pytest.mark.asyncio
    async def test_commit_empty_is_noop(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        await run.tracker.on_messages_published(1)
        await run._commit_events("node", [], track_commit=True)
        assert not await run.tracker.is_quiescent()


class TestGetOutputEvents:
    @pytest.mark.asyncio
    async def test_returns_output_topic_events_under_workflow_consumer(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        await run.topics["agent_output"].publish_data(
            PublishToTopicEvent(
                invoke_context=_ctx(),
                data=[Message(role="assistant", content="done")],
            )
        )

        out = await run._get_output_events()

        assert len(out) == 1
        assert out[0].name == "agent_output"
        assert out[0].consumer_name == run.name


class TestProgressPossible:
    @pytest.mark.asyncio
    async def test_false_when_idle_and_nothing_pending(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        assert await run._progress_possible() is False

    @pytest.mark.asyncio
    async def test_true_when_event_pending_consumption(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        await run.topics["agent_input"].publish_data(_pub())
        assert await run._progress_possible() is True

    @pytest.mark.asyncio
    async def test_true_when_a_node_is_active(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        await run.tracker.enter("node")
        assert await run._progress_possible() is True


# --------------------------------------------------------------------------- #
# run() error handling
# --------------------------------------------------------------------------- #


class TestRunErrorHandling:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("sequential", [False, True])
    async def test_node_failure_raises_node_execution_error(self, sequential):
        wf = _workflow(tool=BoomTool())

        with pytest.raises(NodeExecutionError):
            async for _ in wf.invoke(_pub(), is_sequential=sequential):
                pass

    @pytest.mark.asyncio
    async def test_unexpected_error_is_wrapped_in_workflow_error(self):
        class BoomStore:
            async def get_agent_events(self, assistant_request_id):
                raise RuntimeError("store down")

        run = WorkflowRun(_workflow(), BoomStore())
        with pytest.raises(WorkflowError):
            async for _ in run.run(_pub(), is_sequential=False):
                pass


# --------------------------------------------------------------------------- #
# Definition-level stop forwarding / active-run bookkeeping
# --------------------------------------------------------------------------- #


class TestStopForwarding:
    def test_stop_forwards_to_active_runs(self):
        wf = _workflow()
        run = WorkflowRun(wf, EventStoreInMemory())
        wf._active_runs[id(run)] = run

        wf.stop()

        assert wf._stop_requested
        assert run._stop_requested

    @pytest.mark.asyncio
    async def test_active_runs_cleared_after_invoke(self):
        wf = _workflow()

        _ = [event async for event in wf.invoke(_pub(), is_sequential=False)]

        assert wf._active_runs == {}


# --------------------------------------------------------------------------- #
# Seeding / recovery (init)
# --------------------------------------------------------------------------- #


class TestInit:
    @pytest.mark.asyncio
    async def test_fresh_seeds_input_records_event_and_tracker(self):
        store = EventStoreInMemory()
        run = WorkflowRun(_workflow(), store)

        await run.init(_pub(), is_sequential=False)

        # Input seeded so the subscriber can consume.
        assert await run.topics["agent_input"].can_consume("node")
        # Tracker seeded with the delivery (not quiescent yet).
        assert not await run.tracker.is_quiescent()
        # The seeded publish event was persisted.
        assert len(await store.get_events()) >= 1

    @pytest.mark.asyncio
    async def test_fresh_sequential_enqueues_ready_node(self):
        run = WorkflowRun(_workflow(), EventStoreInMemory())
        await run.init(_pub(), is_sequential=True)
        assert run.nodes["node"] in run.invoke_queue
