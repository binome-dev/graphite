"""Unit tests for the 5-stage HookedNode pipeline (consumer router, hooks, publisher).

These drive ``HookedNode.invoke`` directly with a recording tool and assert the
control-flow branches: fast path, pre-hook DENY/REQUEST, hook chains, consumer
short-circuit (deny + recover-from-store), approve-recovers-proposal, and a
deciding post-hook pause.
"""

import pytest
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import NodeExecutionError
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
from grafi.topics.topic_types import TopicType


@use_command(Command)
class RecordingTool(Tool):
    """A tool that records what it ran on and yields a fixed message."""

    name: str = "RecordingTool"
    type: str = "RecordingTool"
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.TOOL
    output: str = "tool-output"
    invoked: int = 0
    seen: list = []

    async def invoke(self, invoke_context: InvokeContext, input_data: Messages):
        self.invoked += 1
        self.seen.append([m.content for m in input_data])
        yield [Message(role="assistant", content=self.output)]

    def to_dict(self):
        return {"name": self.name, "type": self.type}


class DenyHook(ToolHook):
    """A pre-hook that denies the tool call."""

    async def invoke(self, frame: ToolHookFrame) -> ToolHookFrame:
        frame.decision = Decision.DENY
        return frame


class TagHook(ToolHook):
    """A transform hook that appends a tag to each message (PROCEEDs)."""

    tag: str = "?"

    async def invoke(self, frame: ToolHookFrame) -> ToolHookFrame:
        frame.messages = [
            Message(role=m.role, content=f"{m.content}+{self.tag}")
            for m in frame.messages
        ]
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


def _pause_record(content: str) -> PublishToTopicEvent:
    """A stored pause event, as recorded on the in-workflow-output channel."""
    return PublishToTopicEvent(
        publisher_name="N",
        publisher_type="Node",
        invoke_context=_ctx(),
        name="pause_out",
        type=TopicType.IN_WORKFLOW_OUTPUT_TOPIC_TYPE,
        consumed_event_ids=[],
        data=[Message(role="assistant", content=content)],
    )


async def _run(node: HookedNode, node_input, *, seed=None):
    """Invoke the node under bound services; optionally seed events first."""
    with bind_services(ExecutionServices()):
        for event in seed or []:
            await current_services().event_store.record_event(event)
        return [event async for event in node.invoke(_ctx(), node_input)]


def _output_node(**kwargs) -> HookedNode:
    out = OutputTopic(name="agent_output")
    return HookedNode(
        name="N",
        tool=RecordingTool(seen=[]),
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
        node = _output_node(pre_tool_hooks=[DenyHook()])
        events = await _run(node, [_consume("agent_input", "please run")])
        assert len(events) == 1
        assert events[0].name == ""
        # DENY emits the (unchanged) batch; the tool never runs.
        assert events[0].data[0].content == "please run"
        assert node.tool.invoked == 0

    @pytest.mark.asyncio
    async def test_single_hook_coerced_to_chain(self):
        # A bare ToolHook is accepted as a one-element chain.
        node = _output_node(pre_tool_hooks=DenyHook())
        assert node.pre_tool_hooks == [DenyHook()]
        events = await _run(node, [_consume("agent_input", "x")])
        assert node.tool.invoked == 0 and len(events) == 1

    @pytest.mark.asyncio
    async def test_request_pauses_to_named_channel(self):
        out = OutputTopic(name="agent_output")
        pre_out = Topic(name="pre_hitl_out")
        node = HookedNode(
            name="N",
            tool=RecordingTool(seen=[]),
            pre_tool_hooks=[HITLApprovalHook()],
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

    @pytest.mark.asyncio
    async def test_request_without_pause_route_fails_loudly(self):
        # A REQUESTing hook with no from_stage route must raise a descriptive
        # NodeExecutionError, not an opaque generator RuntimeError.
        node = _output_node(pre_tool_hooks=[HITLApprovalHook()])
        with pytest.raises(NodeExecutionError, match="pause route|pause channel"):
            await _run(node, [_consume("agent_input", "x")])


class TestHookChains:
    @pytest.mark.asyncio
    async def test_transforms_compose_in_declaration_order(self):
        node = _output_node(pre_tool_hooks=[TagHook(tag="a"), TagHook(tag="b")])
        await _run(node, [_consume("agent_input", "msg")])
        # both hooks ran, in order, before the tool
        assert node.tool.seen == [["msg+a+b"]]

    @pytest.mark.asyncio
    async def test_deny_short_circuits_later_hooks(self):
        node = _output_node(
            pre_tool_hooks=[TagHook(tag="a"), DenyHook(), TagHook(tag="never")]
        )
        events = await _run(node, [_consume("agent_input", "msg")])
        # first transform applied, deny stopped the chain, tool skipped
        assert events[0].data[0].content == "msg+a"
        assert node.tool.invoked == 0

    @pytest.mark.asyncio
    async def test_post_chain_transforms_aggregate_and_compose(self):
        node = _output_node(post_tool_hooks=[TagHook(tag="x"), TagHook(tag="y")])
        events = await _run(node, [_consume("agent_input", "msg")])
        assert len(events) == 1
        assert events[0].data[0].content == "tool-output+x+y"


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
        review = _pause_record("reviewed-result")
        node = _output_node(consumer_router=ConsumerRouter(post_hitl_input="post_in"))
        reply = _consume("post_in", "approve", consumed_event_ids=[review.event_id])
        events = await _run(node, [reply], seed=[review])
        assert len(events) == 1
        # The reviewed result is recovered from the store; the tool is not re-run.
        assert events[0].data[0].content == "reviewed-result"
        assert node.tool.invoked == 0
        # Audit edge: the output points at both the reply and the recovered event.
        assert review.event_id in events[0].consumed_event_ids

    @pytest.mark.asyncio
    async def test_post_hitl_approve_without_recoverable_event_raises(self):
        node = _output_node(consumer_router=ConsumerRouter(post_hitl_input="post_in"))
        reply = _consume("post_in", "approve", consumed_event_ids=["missing-id"])
        with pytest.raises(NodeExecutionError, match="could not recover"):
            await _run(node, [reply])


class TestApproveRunsTheProposal:
    """Pre-HITL approve: what was approved is what runs."""

    @pytest.mark.asyncio
    async def test_plain_text_approve_recovers_and_runs_proposal(self):
        proposal = _pause_record("the-proposed-action")
        node = _output_node(consumer_router=ConsumerRouter(pre_hitl_input="pre_in"))
        reply = _consume("pre_in", "yes", consumed_event_ids=[proposal.event_id])
        events = await _run(node, [reply], seed=[proposal])
        assert len(events) == 1
        # The tool ran on the RECOVERED proposal, not on the reply text.
        assert node.tool.invoked == 1
        assert node.tool.seen == [["the-proposed-action"]]
        assert events[0].data[0].content == "tool-output"
        # Audit edge: output points at the reply AND the recovered proposal.
        assert proposal.event_id in events[0].consumed_event_ids

    @pytest.mark.asyncio
    async def test_echoed_call_approve_runs_the_reply(self):
        # A reply that carries a tool call (edit-and-approve) runs as-is.
        proposal = _pause_record("stored-proposal")
        node = _output_node(consumer_router=ConsumerRouter(pre_hitl_input="pre_in"))
        reply = ConsumeFromTopicEvent(
            name="pre_in",
            consumer_name="node",
            consumer_type="Node",
            invoke_context=_ctx(),
            offset=0,
            consumed_event_ids=[proposal.event_id],
            data=[
                Message(
                    role="assistant",
                    content="edited",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "do", "arguments": "{}"},
                        }
                    ],
                )
            ],
        )
        events = await _run(node, [reply], seed=[proposal])
        assert node.tool.invoked == 1
        # The reply's own (edited) payload reached the tool, not the store copy.
        assert node.tool.seen == [["edited"]]
        assert events[0].data[0].content == "tool-output"

    @pytest.mark.asyncio
    async def test_plain_text_approve_without_ids_raises(self):
        # Recovery intended but the resume carried no ids -> loud failure,
        # never a silent run on the reply text.
        node = _output_node(consumer_router=ConsumerRouter(pre_hitl_input="pre_in"))
        reply = _consume("pre_in", "approve")  # no consumed_event_ids
        with pytest.raises(NodeExecutionError, match="could not recover"):
            await _run(node, [reply])
        assert node.tool.invoked == 0

    @pytest.mark.asyncio
    async def test_recovery_ignores_non_pause_events(self):
        # Provenance filter: ids pointing at arbitrary stored events are not
        # replayed as tool input.
        not_a_pause = PublishToTopicEvent(
            publisher_name="N",
            publisher_type="Node",
            invoke_context=_ctx(),
            consumed_event_ids=[],
            data=[Message(role="assistant", content="arbitrary-event")],
        )
        node = _output_node(consumer_router=ConsumerRouter(pre_hitl_input="pre_in"))
        reply = _consume("pre_in", "yes", consumed_event_ids=[not_a_pause.event_id])
        with pytest.raises(NodeExecutionError, match="could not recover"):
            await _run(node, [reply], seed=[not_a_pause])
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
            tool=RecordingTool(seen=[]),
            post_tool_hooks=[HITLApprovalHook()],
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


class TestSerializationStrictness:
    @pytest.mark.asyncio
    async def test_legacy_singular_hook_key_fails_closed(self):
        node = _output_node()
        data = node.to_dict()
        data["pre_tool_hook"] = {"type": "HITLApprovalHook"}  # legacy shape
        with pytest.raises(ValueError, match="legacy singular"):
            await HookedNode.from_dict(
                data, {"agent_output": OutputTopic(name="agent_output")}
            )

    def test_unknown_field_is_rejected(self):
        # extra="forbid": a typo'd gating field must not be silently dropped.
        with pytest.raises(Exception, match="pre_tool_hookz|extra"):
            _output_node(pre_tool_hookz=[DenyHook()])


class TestPostChainDeny:
    @pytest.mark.asyncio
    async def test_post_chain_deny_emits_transformed_batch_and_short_circuits(self):
        node = _output_node(
            post_tool_hooks=[TagHook(tag="x"), DenyHook(), TagHook(tag="never")]
        )
        events = await _run(node, [_consume("agent_input", "msg")])
        assert len(events) == 1
        assert events[0].name == ""  # normal output channel, not a pause channel
        # tool ran once; first transform applied; DENY short-circuited hook 3
        assert events[0].data[0].content == "tool-output+x"
        assert node.tool.invoked == 1


class TestPauseTrustBoundary:
    @pytest.mark.asyncio
    async def test_pause_carries_transformed_frame_and_warns_on_skipped_hooks(self):
        # The human reviews (and recovery later replays) the transformed-so-far
        # frame; hooks declared after the pauser are warned as skipped.
        from loguru import logger

        out = OutputTopic(name="agent_output")
        pre_out = Topic(name="pre_hitl_out")
        node = HookedNode(
            name="N",
            tool=RecordingTool(seen=[]),
            pre_tool_hooks=[TagHook(tag="a"), HITLApprovalHook(), TagHook(tag="never")],
            publisher_router=PublisherRouter(
                routes=[
                    PublishRoute(topic=out),
                    PublishRoute(topic=pre_out, from_stage=Stage.PRE_HOOK),
                ]
            ),
        )
        records: list = []
        sink_id = logger.add(lambda m: records.append(str(m)), level="WARNING")
        try:
            events = await _run(node, [_consume("agent_input", "msg")])
        finally:
            logger.remove(sink_id)
        assert len(events) == 1
        assert events[0].name == "pre_hitl_out"
        # Human-review trust boundary: the reviewer sees exactly what recovery
        # will replay as tool input.
        assert events[0].data[0].content == "msg+a"
        assert node.tool.invoked == 0
        # Hooks after the pauser are skipped now and on resume -> warned.
        assert any("will not run" in r and "TagHook" in r for r in records)


class TestPartialRecovery:
    @pytest.mark.asyncio
    async def test_mixed_ids_recover_the_pause_subset(self):
        # Resume requests commonly reference every output event of the paused
        # invoke; the provenance filter selects the reviewable pause subset and
        # the tool runs on it (normal-output ids are expected and skipped).
        proposal = _pause_record("the-proposed-action")
        normal_output = PublishToTopicEvent(
            publisher_name="N",
            publisher_type="Node",
            invoke_context=_ctx(),
            name="agent_output",
            consumed_event_ids=[],
            data=[Message(role="assistant", content="chat text")],
        )
        node = _output_node(consumer_router=ConsumerRouter(pre_hitl_input="pre_in"))
        reply = _consume(
            "pre_in",
            "yes",
            consumed_event_ids=[normal_output.event_id, proposal.event_id],
        )
        events = await _run(node, [reply], seed=[normal_output, proposal])
        assert node.tool.invoked == 1
        assert node.tool.seen == [["the-proposed-action"]]  # pause subset only
        # Only the recovered pause id joins the output provenance.
        assert proposal.event_id in events[0].consumed_event_ids
        assert normal_output.event_id not in events[0].consumed_event_ids
