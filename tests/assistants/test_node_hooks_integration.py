"""End-to-end integration tests for tool hooks on a hooked node.

These run real ``EventDrivenWorkflow``s (via ``Assistant.invoke``) and cover:

* pre/post tool hooks that TRANSFORM (not just pause) the payload,
* a single node carrying BOTH a pre-hook gate and a post-hook review
  (a two-stage pause/resume on one node).
"""

import uuid
from typing import Callable
from unittest.mock import patch

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.hooks.hitl_approval_hook import HITLApprovalHook
from grafi.nodes.hooks.tool_hook import ToolHook
from grafi.nodes.hooks.tool_hook import ToolHookFrame
from grafi.nodes.impl.hooked_node import HookedNode
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
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


@use_command(Command)
class MockTool(Tool):
    """A tool that yields ``fn(input_data)`` and counts invocations."""

    name: str = "MockTool"
    type: str = "MockTool"
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    fn: Callable[[Messages], Messages]
    invoked: int = 0

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        self.invoked += 1
        yield self.fn(input_data)

    def to_dict(self):
        return {"name": self.name, "type": self.type}


def _echo(input_data: Messages) -> Messages:
    text = " | ".join(str(m.content) for m in input_data if m.content is not None)
    return [Message(role="assistant", content=f"echo[{text}]")]


class PrefixPreHook(ToolHook):
    """A pre-hook that prefixes the input messages and PROCEEDs (no pause)."""

    prefix: str = ">> "

    async def invoke(self, frame: ToolHookFrame) -> ToolHookFrame:
        frame.messages = [
            Message(role=m.role, content=f"{self.prefix}{m.content}")
            for m in frame.messages
        ]
        return frame


class SuffixPostHook(ToolHook):
    """A post-hook that appends a review marker to the tool output and PROCEEDs."""

    async def invoke(self, frame: ToolHookFrame) -> ToolHookFrame:
        frame.messages = [
            Message(role="assistant", content=f"{m.content} [reviewed]")
            for m in frame.messages
        ]
        return frame


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


def _assistant(workflow: EventDrivenWorkflow, name: str = "A") -> Assistant:
    with patch.object(Assistant, "_construct_workflow"):
        return Assistant(name=name, workflow=workflow)


async def _run(assistant: Assistant, text: str):
    outputs = []
    async for event in assistant.invoke(
        PublishToTopicEvent(
            invoke_context=_ctx(), data=[Message(role="user", content=text)]
        )
    ):
        outputs.append(event)
    return outputs


# --------------------------------------------------------------------------- #
# Hook transforms (PROCEED, not a pause)
# --------------------------------------------------------------------------- #
class TestHookTransforms:
    def _single_node_assistant(self, *, pre=None, post=None) -> Assistant:
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        builder = (
            HookedNode.builder()
            .name("N")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(MockTool(fn=_echo))
            .publish_to(agent_output)
        )
        if pre is not None:
            builder.pre_tool_hook(pre)
        if post is not None:
            builder.post_tool_hook(post)
        node = builder.build()
        workflow = EventDrivenWorkflow.builder().name("w").node(node).build()
        return _assistant(workflow)

    @pytest.mark.asyncio
    async def test_pre_hook_transforms_tool_input(self):
        assistant = self._single_node_assistant(pre=PrefixPreHook(prefix=">> "))
        out = await _run(assistant, "hello")
        # the pre-hook prefixed the input the echo tool saw
        assert out[0].data[0].content == "echo[>> hello]"

    @pytest.mark.asyncio
    async def test_post_hook_transforms_tool_output(self):
        assistant = self._single_node_assistant(post=SuffixPostHook())
        out = await _run(assistant, "hello")
        assert out[0].data[0].content == "echo[hello] [reviewed]"

    @pytest.mark.asyncio
    async def test_pre_and_post_hooks_both_transform(self):
        assistant = self._single_node_assistant(
            pre=PrefixPreHook(prefix=">> "), post=SuffixPostHook()
        )
        out = await _run(assistant, "hello")
        assert out[0].data[0].content == "echo[>> hello] [reviewed]"


# --------------------------------------------------------------------------- #
# Pre + post HITL gates on ONE node (two-stage pause/resume)
# --------------------------------------------------------------------------- #
class TestPreAndPostHITLOnOneNode:
    def _assistant(self) -> Assistant:
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        pre_in = InWorkflowInputTopic(name="pre_in")
        post_in = InWorkflowInputTopic(name="post_in")
        pre_out = InWorkflowOutputTopic(
            name="pre_out", paired_in_workflow_input_topic_names=["pre_in"]
        )
        post_out = InWorkflowOutputTopic(
            name="post_out", paired_in_workflow_input_topic_names=["post_in"]
        )
        node = (
            HookedNode.builder()
            .name("GateNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input)
                .or_()
                .subscribed_to(pre_in)
                .or_()
                .subscribed_to(post_in)
                .build()
            )
            # The gated action's result is independent of the approval reply text
            # (the action was decided before the pause; approve just lets it run).
            .tool(
                MockTool(
                    fn=lambda _: [Message(role="assistant", content="action performed")]
                )
            )
            .pre_tool_hook(HITLApprovalHook())
            .post_tool_hook(HITLApprovalHook())
            .consumer_router(
                ConsumerRouter(pre_hitl_input="pre_in", post_hitl_input="post_in")
            )
            .publish_to(agent_output)
            .publish_to(pre_out, from_stage=Stage.PRE_HOOK)
            .publish_to(post_out, from_stage=Stage.POST_HOOK)
            .build()
        )
        workflow = EventDrivenWorkflow.builder().name("two_gate").node(node).build()
        return _assistant(workflow, name="TwoGate")

    @pytest.mark.asyncio
    async def test_pre_gate_then_post_review_then_recover(self):
        assistant = self._assistant()
        node = assistant.workflow.nodes["GateNode"]
        ctx = _ctx()

        # 1) Pre-hook gate pauses; tool has not run.
        first = []
        async for e in assistant.invoke(
            PublishToTopicEvent(
                invoke_context=ctx, data=[Message(role="user", content="act")]
            )
        ):
            first.append(e)
        assert len(first) == 1 and node.tool.invoked == 0

        # 2) Approve the pre-gate -> tool runs -> post-hook pauses for review.
        second = []
        async for e in assistant.invoke(
            PublishToTopicEvent(
                invoke_context=_resume_ctx(ctx),
                data=[Message(role="user", content="approve")],
                consumed_event_ids=[e.event_id for e in first],
            )
        ):
            second.append(e)
        assert len(second) == 1 and node.tool.invoked == 1

        # 3) Approve the post-review -> reviewed result recovered, tool not re-run.
        third = []
        async for e in assistant.invoke(
            PublishToTopicEvent(
                invoke_context=_resume_ctx(ctx),
                data=[Message(role="user", content="approve")],
                consumed_event_ids=[e.event_id for e in second],
            )
        ):
            third.append(e)
        assert len(third) == 1
        assert third[0].data[0].content == "action performed"
        assert node.tool.invoked == 1
