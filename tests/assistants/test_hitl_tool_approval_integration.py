"""Deterministic integration test mirroring ``human_tool_approval_assistant``.

Same single-node HITL fold as the tests_integration example, but with a mock
LLM (so it runs without API keys):

  LLM proposes a tool call -> post-tool hook pauses ONLY tool-call proposals
  (gate_when) -> human verdict via the consumer router:
    approve -> the proposed call is recovered from the event store and routed
               to the function node, which executes it; the LLM then summarizes
    deny    -> the reply is surfaced as the answer; the tool never runs

A plain LLM answer (no tool call) is not gated and flows straight to output.
"""

import uuid
from typing import Callable
from typing import List
from unittest.mock import patch

import pytest
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import Function
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.assistants.assistant import Assistant
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.conditions import has_no_tool_call
from grafi.nodes.conditions import has_tool_call
from grafi.nodes.hooks.hitl_approval_hook import HITLApprovalHook
from grafi.nodes.hooks.hitl_approval_hook import has_tool_call_message
from grafi.nodes.impl.hooked_node import HookedNode
from grafi.nodes.node import Node
from grafi.nodes.routing import ConsumerRouter
from grafi.nodes.routing import Stage
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services
from grafi.tools.command import Command
from grafi.tools.command import use_command
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.llm import LLM
from grafi.tools.tool import Tool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


@use_command(Command)
class MockLLMTool(Tool):
    """A deterministic stand-in for an LLM node."""

    name: str = "MockLLMTool"
    type: str = "MockLLMTool"
    role: str = "assistant"
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    fn: Callable[[Messages], Messages]

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        yield self.fn(input_data)

    def to_dict(self):
        return {"name": self.name, "type": self.type}


def _tool_call(name: str, args: str) -> ChatCompletionMessageToolCall:
    return ChatCompletionMessageToolCall(
        id="call_1", type="function", function=Function(name=name, arguments=args)
    )


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


def _build_assistant():
    calls = {"llm": 0, "tool": 0}

    def mock_llm(messages: List[Message]) -> List[Message]:
        calls["llm"] += 1
        if calls["llm"] >= 2:
            # After the tool ran, summarize.
            return [Message(role="assistant", content="Action completed.")]
        content = (messages[-1].content or "") if messages else ""
        if "act" in content.lower():
            # The model justifies the call via the injected tool_call_reason arg.
            return [
                Message(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        _tool_call(
                            "do_action",
                            '{"target": "x", "tool_call_reason": "the user asked"}',
                        )
                    ],
                )
            ]
        return [Message(role="assistant", content="No action needed.")]

    def do_action(self, target: str) -> str:
        calls["tool"] += 1
        return f"performed action on {target}"

    agent_input = InputTopic(name="agent_input_topic")
    agent_output = OutputTopic(name="agent_output_topic")
    function_call_topic = Topic(name="tool_call_topic")
    function_output_topic = Topic(name="tool_result_topic")
    human_response = InWorkflowInputTopic(name="human_response_topic")
    human_request = InWorkflowOutputTopic(
        name="tool_call_request_topic",
        paired_in_workflow_input_topic_names=["human_response_topic"],
    )

    llm_node = (
        HookedNode.builder()
        .name("LLMNode")
        .subscribe(
            SubscriptionBuilder()
            .subscribed_to(agent_input)
            .or_()
            .subscribed_to(function_output_topic)
            .or_()
            .subscribed_to(human_response)
            .build()
        )
        .tool(MockLLMTool(fn=mock_llm))
        .post_tool_hook(HITLApprovalHook(gate_when=has_tool_call_message))
        .consumer_router(ConsumerRouter(post_hitl_input="human_response_topic"))
        .publish_to(function_call_topic, when=has_tool_call)
        .publish_to(agent_output, when=has_no_tool_call)
        .publish_to(human_request, from_stage=Stage.POST_HOOK)
        .build()
    )
    function_node = (
        # HookedNode so the reserved tool_call_reason arg is stripped before
        # the function runs.
        HookedNode.builder()
        .name("FunctionNode")
        .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
        .tool(FunctionCallTool.builder().name("Action").function(do_action).build())
        .publish_to(function_output_topic)
        .build()
    )
    workflow = (
        EventDrivenWorkflow.builder()
        .name("tool_approval")
        .node(llm_node)
        .node(function_node)
        .build()
    )
    with patch.object(Assistant, "_construct_workflow"):
        assistant = Assistant(name="ToolApproval", workflow=workflow)
    return assistant, calls


async def _invoke(assistant, ctx, text, consumed=None):
    out = []
    async for event in assistant.invoke(
        PublishToTopicEvent(
            invoke_context=ctx,
            data=[Message(role="user", content=text)],
            consumed_event_ids=consumed or [],
        )
    ):
        out.append(event)
    return out


class TestToolApprovalHITL:
    @pytest.mark.asyncio
    async def test_approve_runs_tool_then_summarizes(self):
        assistant, calls = _build_assistant()
        ctx = _ctx()

        first = await _invoke(assistant, ctx, "please act on x")
        assert len(first) == 1  # paused for approval
        assert calls["tool"] == 0  # not yet executed
        # the reason rides in the proposed call surfaced to the reviewer
        assert "the user asked" in first[0].data[0].tool_calls[0].function.arguments

        second = await _invoke(
            assistant,
            _resume_ctx(ctx),
            "YES",
            consumed=[e.event_id for e in first],
        )
        assert len(second) == 1
        assert second[0].data[0].content == "Action completed."
        # the tool ran -> tool_call_reason was stripped before calling do_action
        assert calls["tool"] == 1

    @pytest.mark.asyncio
    async def test_deny_surfaces_reply_and_skips_tool(self):
        assistant, calls = _build_assistant()
        ctx = _ctx()

        first = await _invoke(assistant, ctx, "please act on x")
        assert len(first) == 1

        second = await _invoke(
            assistant,
            _resume_ctx(ctx),
            "NO, do not",
            consumed=[e.event_id for e in first],
        )
        assert len(second) == 1
        assert "NO, do not" in second[0].data[0].content
        assert calls["tool"] == 0  # denied -> tool never ran

    @pytest.mark.asyncio
    async def test_plain_answer_is_not_gated(self):
        assistant, calls = _build_assistant()
        out = await _invoke(assistant, _ctx(), "just say hello")
        # No tool call proposed -> gate_when is False -> no pause, direct answer.
        assert len(out) == 1
        assert out[0].data[0].content == "No action needed."
        assert calls["tool"] == 0


class _MockLLM(LLM):
    """A minimal real ``LLM`` (so the function-spec wiring treats it as one)."""

    name: str = "MockLLM"
    type: str = "MockLLM"

    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        yield [Message(role="assistant", content="x")]

    def to_dict(self):
        return {"name": self.name, "type": self.type}


def _do_action(self, target: str) -> str:
    return f"did {target}"


class TestReasonSpecWiring:
    def test_hook_augments_llm_function_specs_at_build(self):
        # A HITLApprovalHook on an LLM node injects tool_call_reason into the
        # function specs linked from its function node, at workflow build time.
        agent_input = InputTopic(name="agent_input_topic")
        agent_output = OutputTopic(name="agent_output_topic")
        function_call_topic = Topic(name="tool_call_topic")
        function_output_topic = Topic(name="tool_result_topic")

        llm_node = (
            HookedNode.builder()
            .name("LLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(_MockLLM())
            .post_tool_hook(HITLApprovalHook(gate_when=has_tool_call_message))
            .publish_to(function_call_topic, when=has_tool_call)
            .publish_to(agent_output, when=has_no_tool_call)
            .build()
        )
        function_node = (
            Node.builder()
            .name("FunctionNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder().name("Action").function(_do_action).build()
            )
            .publish_to(function_output_topic)
            .build()
        )
        EventDrivenWorkflow.builder().name("w").node(llm_node).node(
            function_node
        ).build()

        specs = llm_node.tool.get_function_specs()
        assert specs, "function spec should be linked onto the LLM node"
        assert all("tool_call_reason" in s.parameters.properties for s in specs)
        assert all("tool_call_reason" in s.parameters.required for s in specs)

    def test_no_hook_leaves_specs_unaugmented(self):
        agent_input = InputTopic(name="agent_input_topic")
        agent_output = OutputTopic(name="agent_output_topic")
        function_call_topic = Topic(name="tool_call_topic")
        function_output_topic = Topic(name="tool_result_topic")

        llm_node = (
            Node.builder()
            .name("LLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(_MockLLM())  # no hook
            .publish_to(function_call_topic, when=has_tool_call)
            .publish_to(agent_output, when=has_no_tool_call)
            .build()
        )
        function_node = (
            Node.builder()
            .name("FunctionNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(
                FunctionCallTool.builder().name("Action").function(_do_action).build()
            )
            .publish_to(function_output_topic)
            .build()
        )
        EventDrivenWorkflow.builder().name("w2").node(llm_node).node(
            function_node
        ).build()

        specs = llm_node.tool.get_function_specs()
        assert specs
        assert all("tool_call_reason" not in s.parameters.properties for s in specs)


class TestNodeStripsReason:
    @pytest.mark.asyncio
    async def test_node_strips_reserved_reason_before_tool(self):
        # The strip lives at the hooked node (orchestration) boundary, not in
        # the tool: the function tool receives clean args.
        agent_input = InputTopic(name="agent_input_topic")
        agent_output = OutputTopic(name="agent_output_topic")
        node = (
            HookedNode.builder()
            .name("FunctionNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(
                FunctionCallTool.builder().name("Action").function(_do_action).build()
            )
            .publish_to(agent_output)
            .build()
        )
        tool_call_event = ConsumeFromTopicEvent(
            name="agent_input_topic",
            consumer_name="FunctionNode",
            consumer_type="Node",
            invoke_context=_ctx(),
            offset=0,
            consumed_event_ids=[],
            data=[
                Message(
                    role="assistant",
                    tool_calls=[
                        _tool_call(
                            "_do_action",
                            '{"target": "x", "tool_call_reason": "because"}',
                        )
                    ],
                )
            ],
        )
        with bind_services(ExecutionServices()):
            out = [event async for event in node.invoke(_ctx(), [tool_call_event])]
        # do_action(target="x") ran; the reserved reason arg did not reach it
        assert out[0].data[0].content == "did x"
