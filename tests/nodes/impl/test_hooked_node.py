"""Unit tests for the 5-stage HookedNode pipeline (consumer router, hooks, publisher).

These drive ``HookedNode.invoke`` directly with a recording tool and assert the
control-flow branches: fast path, pre-hook DENY/REQUEST, consumer short-circuit
(deny + recover-from-store), and a deciding post-hook pause.
"""

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.nodes.hooks.hitl_approval_hook import HITLApprovalHook
from grafi.nodes.hooks.tool_hook import ToolHook
from grafi.nodes.hooks.tool_hook import ToolHookFrame
from grafi.nodes.impl.hooked_node import HookedNode
from grafi.nodes.node_base import PublisherRouter
from grafi.nodes.node_base import PublishRoute
from grafi.nodes.routing import ConsumerRouter
from grafi.nodes.routing import Decision
from grafi.nodes.routing import Entry
from grafi.nodes.routing import Stage
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services
from grafi.runtime.execution_services import current_services
from grafi.tools.command import Command
from grafi.tools.command import use_command
from grafi.tools.tool import Tool
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic


@use_command(Command)
class RecordingTool(Tool):
    """A tool that records whether it ran and yields a fixed message."""

    name: str = "RecordingTool"
    type: str = "RecordingTool"
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    output: str = "tool-output"
    invoked: int = 0

    async def invoke(self, invoke_context: InvokeContext, input_data: Messages):
        self.invoked += 1
        yield [Message(role="assistant", content=self.output)]

    def to_dict(self):
        return {"name": self.name, "type": self.type}


class DenyHook(ToolHook):
    """A pre-hook that denies the tool call."""

    async def invoke(self, frame: ToolHookFrame) -> ToolHookFrame:
        frame.decision = Decision.DENY
        return frame


def _ctx() -> InvokeContext:
    return InvokeContext(conversation_id="c", invoke_id="i", assistant_request_id="r")


def _consume(name: str, content: str, consumed_event_ids=None) -> ConsumeFromTopicEvent:
    return ConsumeFromTopicEvent(
        name=name,
        consumer_name="node",
        consumer_type="Node",
        invoke_context=_ctx(),
        offset=0,
        consumed_event_ids=consumed_event_ids or [],
        data=[Message(role="user", content=content)],
    )


async def _run(node: HookedNode, node_input, *, seed=None):
    """Invoke the node under bound services; optionally seed an event first."""
    with bind_services(ExecutionServices()):
        if seed is not None:
            await current_services().event_store.record_event(seed)
        return [event async for event in node.invoke(_ctx(), node_input)]


def _output_node(**kwargs) -> HookedNode:
    out = OutputTopic(name="agent_output")
    return HookedNode(
        name="N",
        tool=RecordingTool(),
        publisher_router=PublisherRouter(routes=[PublishRoute(topic=out)]),
        **kwargs,
    )


class TestFastPath:
    @pytest.mark.asyncio
    async def test_default_node_emits_content_routed_event(self):
        node = _output_node()
        events = await _run(node, [_consume("agent_input", "hello")])
        assert len(events) == 1
        # name="" -> content-routed by the publisher router
        assert events[0].name == ""
        assert events[0].data[0].content == "tool-output"
        assert node.tool.invoked == 1


class TestPreHook:
    @pytest.mark.asyncio
    async def test_deny_forwards_reply_and_skips_tool(self):
        node = _output_node(pre_tool_hook=DenyHook())
        events = await _run(node, [_consume("agent_input", "please run")])
        assert len(events) == 1
        assert events[0].name == ""
        # DENY emits the (unchanged) batch; the tool never runs.
        assert events[0].data[0].content == "please run"
        assert node.tool.invoked == 0

    @pytest.mark.asyncio
    async def test_request_pauses_to_named_channel(self):
        out = OutputTopic(name="agent_output")
        pre_out = Topic(name="pre_hitl_out")
        node = HookedNode(
            name="N",
            tool=RecordingTool(),
            pre_tool_hook=HITLApprovalHook(),
            publisher_router=PublisherRouter(
                routes=[
                    PublishRoute(topic=out),
                    PublishRoute(topic=pre_out, from_stage=Stage.PRE_HOOK),
                ]
            ),
        )
        events = await _run(node, [_consume("agent_input", "do risky thing")])
        assert len(events) == 1
        # The pause is directed by name to the pre-hook channel.
        assert events[0].name == "pre_hitl_out"
        assert node.tool.invoked == 0


class TestConsumerShortCircuit:
    @pytest.mark.asyncio
    async def test_pre_hitl_deny_forwards_reply(self):
        node = _output_node(consumer_router=ConsumerRouter(pre_hitl_input="pre_in"))
        events = await _run(node, [_consume("pre_in", "no")])
        assert len(events) == 1
        assert events[0].name == ""
        assert events[0].data[0].content == "no"
        assert node.tool.invoked == 0

    @pytest.mark.asyncio
    async def test_post_hitl_approve_recovers_from_store(self):
        review = PublishToTopicEvent(
            publisher_name="N",
            publisher_type="Node",
            invoke_context=_ctx(),
            consumed_event_ids=[],
            data=[Message(role="assistant", content="reviewed-result")],
        )
        node = _output_node(consumer_router=ConsumerRouter(post_hitl_input="post_in"))
        reply = _consume("post_in", "approve", consumed_event_ids=[review.event_id])
        events = await _run(node, [reply], seed=review)
        assert len(events) == 1
        # The reviewed result is recovered from the store; the tool is not re-run.
        assert events[0].data[0].content == "reviewed-result"
        assert node.tool.invoked == 0


class TestConsumerSourceRouting:
    @pytest.mark.asyncio
    async def test_routed_source_skips_tool_and_forwards(self):
        # messages from "bypass" are routed straight to the publisher
        node = _output_node(
            consumer_router=ConsumerRouter(source_routes={"bypass": Entry.PUBLISHER})
        )
        events = await _run(node, [_consume("bypass", "passthrough me")])
        assert len(events) == 1
        assert (
            events[0].data[0].content == "passthrough me"
        )  # forwarded, not tool output
        assert node.tool.invoked == 0

    @pytest.mark.asyncio
    async def test_unrouted_source_runs_tool(self):
        # a different source on the same node falls through to the tool path
        node = _output_node(
            consumer_router=ConsumerRouter(source_routes={"bypass": Entry.PUBLISHER})
        )
        events = await _run(node, [_consume("agent_input", "hello")])
        assert len(events) == 1
        assert events[0].data[0].content == "tool-output"
        assert node.tool.invoked == 1


class TestPostHook:
    @pytest.mark.asyncio
    async def test_deciding_post_hook_pauses(self):
        out = OutputTopic(name="agent_output")
        post_out = Topic(name="post_hitl_out")
        node = HookedNode(
            name="N",
            tool=RecordingTool(),
            post_tool_hook=HITLApprovalHook(),
            publisher_router=PublisherRouter(
                routes=[
                    PublishRoute(topic=out),
                    PublishRoute(topic=post_out, from_stage=Stage.POST_HOOK),
                ]
            ),
        )
        events = await _run(node, [_consume("agent_input", "compute")])
        assert len(events) == 1
        # Tool ran, then the post-hook requested review -> directed pause.
        assert node.tool.invoked == 1
        assert events[0].name == "post_hitl_out"
