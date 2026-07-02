"""End-to-end HITL on a SINGLE node, folded via the new routing components.

One node carries the whole approval gate:
  - pre_tool_hook = HITLApprovalHook  -> REQUEST a pause before the tool runs
  - publisher route (from_stage=PRE_HOOK) -> pauses to an InWorkflowOutputTopic
  - consumer_router(pre_hitl_input=...) -> classifies the human reply's verdict
      approve (echoed tool call) -> run the gated tool
      deny (plain text)          -> forward the reply (a denial), tool not run

Exercises the UNCHANGED pause/resume machinery (in-workflow topic pairing +
run_recovery._reissue_paired_inputs) through the real EventDrivenWorkflow.
"""

import json
import uuid
from unittest.mock import patch

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import WorkflowError
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.hooks.hitl_approval_hook import HITLApprovalHook
from grafi.nodes.hooks.hook_factory import hook_from_dict
from grafi.nodes.impl.hooked_node import HookedNode
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.routing import ConsumerRouter
from grafi.nodes.routing import Stage
from grafi.tools.command import Command
from grafi.tools.command import use_command
from grafi.tools.tool import Tool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


@use_command(Command)
class ActionTool(Tool):
    """The gated action: records that it ran and returns a result message."""

    name: str = "ActionTool"
    type: str = "ActionTool"
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    invoked: int = 0

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.invoked += 1
        yield [Message(role="assistant", content="action performed")]

    def to_dict(self):
        return {"name": self.name, "type": self.type}


def _build_assistant() -> Assistant:
    agent_input = InputTopic(name="agent_input")
    agent_output = OutputTopic(name="agent_output")
    hitl_in = InWorkflowInputTopic(name="hitl_in")
    hitl_out = InWorkflowOutputTopic(
        name="hitl_out",
        paired_in_workflow_input_topic_names=["hitl_in"],
    )

    node = (
        HookedNode.builder()
        .name("ApprovalNode")
        .subscribe(
            SubscriptionBuilder()
            .subscribed_to(agent_input)
            .or_()
            .subscribed_to(hitl_in)
            .build()
        )
        .tool(ActionTool())
        .pre_tool_hook(HITLApprovalHook())
        .consumer_router(ConsumerRouter(pre_hitl_input="hitl_in"))
        .publish_to(agent_output)
        .publish_to(hitl_out, from_stage=Stage.PRE_HOOK)
        .build()
    )

    workflow = EventDrivenWorkflow.builder().name("single_node_hitl").node(node).build()

    with patch.object(Assistant, "_construct_workflow"):
        return Assistant(name="HITLAssistant", workflow=workflow)


def _ctx() -> InvokeContext:
    return InvokeContext(
        conversation_id=uuid.uuid4().hex,
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
    )


def _resume_ctx(ctx: InvokeContext) -> InvokeContext:
    return InvokeContext(
        conversation_id=ctx.conversation_id,
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=ctx.assistant_request_id,
    )


async def _first_invoke(assistant: Assistant, ctx: InvokeContext):
    """Propose an action and pause at the approval gate."""
    outputs = []
    async for event in assistant.invoke(
        PublishToTopicEvent(
            invoke_context=ctx,
            data=[Message(role="user", content="please perform the action")],
        )
    ):
        outputs.append(event)
    return outputs


class TestSingleNodeHITL:
    @pytest.mark.asyncio
    async def test_pre_hook_pauses_then_approve_runs_tool(self):
        assistant = _build_assistant()
        node = assistant.workflow.nodes["ApprovalNode"]
        ctx = _ctx()

        # 1) First invoke pauses at the gate, surfacing the HITL request.
        first = await _first_invoke(assistant, ctx)
        assert len(first) == 1
        assert node.tool.invoked == 0  # gated -- tool has NOT run yet

        # 2) Human approves by echoing the proposed call back.
        approve = PublishToTopicEvent(
            invoke_context=_resume_ctx(ctx),
            data=[Message(role="user", content="approve")],
            consumed_event_ids=[event.event_id for event in first],
        )
        second = []
        async for event in assistant.invoke(approve):
            second.append(event)

        assert len(second) == 1
        assert second[0].data[0].content == "action performed"
        assert node.tool.invoked == 1  # approved -> the gated tool ran

    @pytest.mark.asyncio
    async def test_pre_hook_deny_forwards_reply_without_running_tool(self):
        assistant = _build_assistant()
        node = assistant.workflow.nodes["ApprovalNode"]
        ctx = _ctx()

        first = await _first_invoke(assistant, ctx)
        assert len(first) == 1

        # Human denies with plain text.
        deny = PublishToTopicEvent(
            invoke_context=_resume_ctx(ctx),
            data=[Message(role="user", content="no, do not")],
            consumed_event_ids=[event.event_id for event in first],
        )
        second = []
        async for event in assistant.invoke(deny):
            second.append(event)

        assert len(second) == 1
        assert "no, do not" in second[0].data[0].content
        assert node.tool.invoked == 0  # denied -> tool never ran


def _build_post_review_assistant() -> Assistant:
    agent_input = InputTopic(name="agent_input")
    agent_output = OutputTopic(name="agent_output")
    hitl_in = InWorkflowInputTopic(name="hitl_in")
    hitl_out = InWorkflowOutputTopic(
        name="hitl_out",
        paired_in_workflow_input_topic_names=["hitl_in"],
    )

    node = (
        HookedNode.builder()
        .name("ReviewNode")
        .subscribe(
            SubscriptionBuilder()
            .subscribed_to(agent_input)
            .or_()
            .subscribed_to(hitl_in)
            .build()
        )
        .tool(ActionTool())
        .post_tool_hook(HITLApprovalHook())
        .consumer_router(ConsumerRouter(post_hitl_input="hitl_in"))
        .publish_to(agent_output)
        .publish_to(hitl_out, from_stage=Stage.POST_HOOK)
        .build()
    )

    workflow = EventDrivenWorkflow.builder().name("post_review_hitl").node(node).build()
    with patch.object(Assistant, "_construct_workflow"):
        return Assistant(name="PostReviewAssistant", workflow=workflow)


class TestSingleNodePostReview:
    @pytest.mark.asyncio
    async def test_post_hook_pauses_then_approve_recovers_result(self):
        assistant = _build_post_review_assistant()
        node = assistant.workflow.nodes["ReviewNode"]
        ctx = _ctx()

        # 1) Tool runs, then the post-hook pauses for review of the result.
        first = await _first_invoke(assistant, ctx)
        assert len(first) == 1
        assert node.tool.invoked == 1  # the tool ran before the review pause
        assert first[0].data[0].content == "action performed"

        # 2) Approve -> the reviewed result is recovered from the store, not re-run.
        approve = PublishToTopicEvent(
            invoke_context=_resume_ctx(ctx),
            data=[Message(role="user", content="approve")],
            consumed_event_ids=[event.event_id for event in first],
        )
        second = []
        async for event in assistant.invoke(approve):
            second.append(event)

        assert len(second) == 1
        assert second[0].data[0].content == "action performed"
        assert node.tool.invoked == 1  # NOT re-run on resume (recover-from-store)

    @pytest.mark.asyncio
    async def test_post_hook_deny_forwards_reply(self):
        assistant = _build_post_review_assistant()
        node = assistant.workflow.nodes["ReviewNode"]
        ctx = _ctx()

        first = await _first_invoke(assistant, ctx)
        assert len(first) == 1
        assert node.tool.invoked == 1

        deny = PublishToTopicEvent(
            invoke_context=_resume_ctx(ctx),
            data=[Message(role="user", content="reject it")],
            consumed_event_ids=[event.event_id for event in first],
        )
        second = []
        async for event in assistant.invoke(deny):
            second.append(event)

        assert len(second) == 1
        assert "reject it" in second[0].data[0].content
        assert node.tool.invoked == 1  # ran once; not re-run on deny

    @pytest.mark.asyncio
    async def test_recover_works_on_sequential_engine_too(self):
        # Covers the sequential engine's get_node_input consumed_event_ids path.
        assistant = _build_post_review_assistant()
        node = assistant.workflow.nodes["ReviewNode"]
        ctx = _ctx()

        first = []
        async for event in assistant.invoke(
            PublishToTopicEvent(
                invoke_context=ctx,
                data=[Message(role="user", content="go")],
            ),
            is_sequential=True,
        ):
            first.append(event)
        assert len(first) == 1 and node.tool.invoked == 1

        approve = PublishToTopicEvent(
            invoke_context=_resume_ctx(ctx),
            data=[Message(role="user", content="approve")],
            consumed_event_ids=[event.event_id for event in first],
        )
        second = []
        async for event in assistant.invoke(approve, is_sequential=True):
            second.append(event)
        assert len(second) == 1
        assert second[0].data[0].content == "action performed"
        assert node.tool.invoked == 1


def _hitl_node() -> HookedNode:
    agent_input = InputTopic(name="agent_input")
    agent_output = OutputTopic(name="agent_output")
    hitl_in = InWorkflowInputTopic(name="hitl_in")
    hitl_out = InWorkflowOutputTopic(
        name="hitl_out", paired_in_workflow_input_topic_names=["hitl_in"]
    )
    return (
        HookedNode.builder()
        .name("ApprovalNode")
        .subscribe(
            SubscriptionBuilder()
            .subscribed_to(agent_input)
            .or_()
            .subscribed_to(hitl_in)
            .build()
        )
        .tool(ActionTool())
        .pre_tool_hook(HITLApprovalHook())
        .consumer_router(ConsumerRouter(pre_hitl_input="hitl_in"))
        .publish_to(agent_output)
        .publish_to(hitl_out, from_stage=Stage.PRE_HOOK)
        .build()
    )


class TestRouterValidation:
    def test_consumer_input_not_subscribed_raises(self):
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        node = (
            HookedNode.builder()
            .name("N")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(ActionTool())
            .consumer_router(ConsumerRouter(pre_hitl_input="hitl_in"))
            .publish_to(agent_output)
            .build()
        )
        with pytest.raises(WorkflowError, match="not subscribed"):
            EventDrivenWorkflow.builder().name("bad").node(node).build()

    def test_pause_route_to_plain_topic_raises(self):
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        plain = Topic(name="plain_pause")
        node = (
            HookedNode.builder()
            .name("N")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(ActionTool())
            .publish_to(agent_output)
            .publish_to(plain, from_stage=Stage.PRE_HOOK)
            .build()
        )
        with pytest.raises(WorkflowError, match="InWorkflowOutputTopic"):
            EventDrivenWorkflow.builder().name("bad").node(node).build()


class TestHITLSerialization:
    def test_node_serializes_routing_components(self):
        node = _hitl_node()
        data = json.loads(json.dumps(node.to_dict()))

        # The new routing components are present in the manifest.
        assert data["consumer_router"]["pre_hitl_input"] == "hitl_in"
        assert [h["type"] for h in data["pre_tool_hooks"]] == ["HITLApprovalHook"]
        assert "pre_hook" in [
            r["from_stage"] for r in data["publisher_router"]["routes"]
        ]

        # ...and reconstruct from it.
        topics = {t.name: t for t in node.publish_to}
        topics["hitl_in"] = node._subscribed_topics["hitl_in"]
        restored_consumer = ConsumerRouter.from_dict(data["consumer_router"])
        restored_publisher = PublisherRouter.from_dict(data["publisher_router"], topics)
        restored_hook = hook_from_dict(data["pre_tool_hooks"][0])

        assert restored_consumer.pre_hitl_input == "hitl_in"
        assert isinstance(restored_hook, HITLApprovalHook)
        assert any(r.from_stage is Stage.PRE_HOOK for r in restored_publisher.routes)

    def test_shared_pre_and_post_channel_raises(self):
        # classify checks the pre channel first, so a shared channel would
        # misroute post-pause approvals into re-running the tool.
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        hitl_in = InWorkflowInputTopic(name="hitl_in")
        node = (
            HookedNode.builder()
            .name("N")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(hitl_in)
                .build()
            )
            .tool(ActionTool())
            .consumer_router(
                ConsumerRouter(pre_hitl_input="hitl_in", post_hitl_input="hitl_in")
            )
            .publish_to(agent_output)
            .build()
        )
        with pytest.raises(WorkflowError, match="both pre_hitl_input and"):
            EventDrivenWorkflow.builder().name("bad").node(node).build()

    def test_unconditional_pause_without_resume_classification_raises(self):
        # Pause-loop: the node subscribes its own resume input but never
        # classifies it, so every reply would re-enter and pause forever.
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        hitl_in = InWorkflowInputTopic(name="hitl_in")
        hitl_out = InWorkflowOutputTopic(
            name="hitl_out", paired_in_workflow_input_topic_names=["hitl_in"]
        )
        node = (
            HookedNode.builder()
            .name("N")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(hitl_in)
                .build()
            )
            .tool(ActionTool())
            .pre_tool_hook(HITLApprovalHook())  # unconditional pause
            # NOTE: no consumer_router -- replies are never classified
            .publish_to(agent_output)
            .publish_to(hitl_out, from_stage=Stage.PRE_HOOK)
            .build()
        )
        with pytest.raises(WorkflowError, match="pause again forever"):
            EventDrivenWorkflow.builder().name("bad").node(node).build()

    def test_source_routes_classification_satisfies_pause_loop_rule(self):
        # A source_routes entry for the paired input is a legitimate wiring.
        from grafi.nodes.routing import Entry

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        hitl_in = InWorkflowInputTopic(name="hitl_in")
        hitl_out = InWorkflowOutputTopic(
            name="hitl_out", paired_in_workflow_input_topic_names=["hitl_in"]
        )
        node = (
            HookedNode.builder()
            .name("N")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(hitl_in)
                .build()
            )
            .tool(ActionTool())
            .pre_tool_hook(HITLApprovalHook())
            .consumer_router(ConsumerRouter(source_routes={"hitl_in": Entry.PUBLISHER}))
            .publish_to(agent_output)
            .publish_to(hitl_out, from_stage=Stage.PRE_HOOK)
            .build()
        )
        # builds without raising
        EventDrivenWorkflow.builder().name("ok").node(node).build()


class TestResumeIdempotency:
    @pytest.mark.asyncio
    async def test_replayed_approve_does_not_rerun_the_tool(self):
        # A crash-replayed or repeated resume request must not double-execute
        # the approved side-effecting tool (at-least-once -> at-most-once per
        # approval).
        assistant = _build_assistant()
        node = assistant.workflow.nodes["ApprovalNode"]
        ctx = _ctx()

        first = await _first_invoke(assistant, ctx)
        assert node.tool.invoked == 0

        approve = PublishToTopicEvent(
            invoke_context=_resume_ctx(ctx),
            data=[Message(role="user", content="approve")],
            consumed_event_ids=[event.event_id for event in first],
        )
        second = []
        async for event in assistant.invoke(approve):
            second.append(event)
        assert node.tool.invoked == 1  # approved -> ran once

        # Replay the SAME resume request (same consumed_event_ids).
        replay = PublishToTopicEvent(
            invoke_context=_resume_ctx(ctx),
            data=[Message(role="user", content="approve")],
            consumed_event_ids=[event.event_id for event in first],
        )
        third = []
        async for event in assistant.invoke(replay):
            third.append(event)

        # The duplicate reissue was skipped: the tool did NOT run again.
        assert node.tool.invoked == 1

    @pytest.mark.asyncio
    async def test_deny_then_changed_mind_approve_still_runs(self):
        # The idempotency guard must not swallow a changed-mind reply about the
        # SAME pause: a deny followed by an approve (different payload, same
        # consumed_event_ids) reissues normally and runs the gated tool.
        assistant = _build_assistant()
        node = assistant.workflow.nodes["ApprovalNode"]
        ctx = _ctx()

        first = await _first_invoke(assistant, ctx)
        pause_ids = [event.event_id for event in first]

        deny = PublishToTopicEvent(
            invoke_context=_resume_ctx(ctx),
            data=[Message(role="user", content="no, hold off")],
            consumed_event_ids=pause_ids,
        )
        second = []
        async for event in assistant.invoke(deny):
            second.append(event)
        assert node.tool.invoked == 0  # denied

        approve = PublishToTopicEvent(
            invoke_context=_resume_ctx(ctx),
            data=[Message(role="user", content="approve")],
            consumed_event_ids=pause_ids,
        )
        third = []
        async for event in assistant.invoke(approve):
            third.append(event)

        # The changed-mind approval went through: the gated tool ran.
        assert node.tool.invoked == 1
        assert any(e.data[0].content == "action performed" for e in third)


class TestGatedRevisionLoopValidation:
    def test_gated_hook_with_unrouted_resume_input_builds_with_warning(self):
        # A gate_when-conditioned HITL hook can be a deliberate revision loop:
        # the workflow must BUILD (warning only), not hard-fail.
        from loguru import logger

        from grafi.nodes.hooks.hitl_approval_hook import has_tool_call_message

        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        hitl_in = InWorkflowInputTopic(name="hitl_in")
        hitl_out = InWorkflowOutputTopic(
            name="hitl_out", paired_in_workflow_input_topic_names=["hitl_in"]
        )
        node = (
            HookedNode.builder()
            .name("N")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(hitl_in)
                .build()
            )
            .tool(ActionTool())
            .pre_tool_hook(HITLApprovalHook(gate_when=has_tool_call_message))
            # No consumer_router: replies re-enter the (gated) pipeline.
            .publish_to(agent_output)
            .publish_to(hitl_out, from_stage=Stage.PRE_HOOK)
            .build()
        )
        records: list = []
        sink_id = logger.add(lambda m: records.append(str(m)), level="WARNING")
        try:
            EventDrivenWorkflow.builder().name("revision_loop").node(node).build()
        finally:
            logger.remove(sink_id)
        assert any("revision loop" in r or "re-enter" in r for r in records)
