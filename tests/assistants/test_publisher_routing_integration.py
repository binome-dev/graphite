"""End-to-end integration tests for the node's publisher router.

These run real ``EventDrivenWorkflow``s (via ``Assistant.invoke``) and cover
publisher-router behaviour: content routing to different consumers, fan-out to
several consumers, and a no-matching-route drop.
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
from grafi.nodes.node import Node
from grafi.tools.command import Command
from grafi.tools.command import use_command
from grafi.tools.tool import Tool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
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


def _ctx() -> InvokeContext:
    return InvokeContext(
        conversation_id=uuid.uuid4().hex,
        invoke_id=uuid.uuid4().hex,
        assistant_request_id=uuid.uuid4().hex,
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


def _contains(token: str) -> Callable:
    return lambda event: token in (event.data[-1].content or "")


class TestPublisherRouting:
    def _content_split_assistant(self) -> Assistant:
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        to_x = Topic(name="to_x")
        to_y = Topic(name="to_y")

        def route(input_data: Messages) -> Messages:
            content = input_data[-1].content or ""
            tag = "X" if "x" in content.lower() else "Y"
            return [Message(role="assistant", content=f"payload-{tag}")]

        router = (
            Node.builder()
            .name("Router")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(MockTool(fn=route))
            .publish_to(to_x, when=_contains("payload-X"))
            .publish_to(to_y, when=_contains("payload-Y"))
            .build()
        )
        node_x = (
            Node.builder()
            .name("HandlerX")
            .subscribe(SubscriptionBuilder().subscribed_to(to_x).build())
            .tool(
                MockTool(
                    fn=lambda _: [Message(role="assistant", content="handled by X")]
                )
            )
            .publish_to(agent_output)
            .build()
        )
        node_y = (
            Node.builder()
            .name("HandlerY")
            .subscribe(SubscriptionBuilder().subscribed_to(to_y).build())
            .tool(
                MockTool(
                    fn=lambda _: [Message(role="assistant", content="handled by Y")]
                )
            )
            .publish_to(agent_output)
            .build()
        )
        workflow = (
            EventDrivenWorkflow.builder()
            .name("split")
            .node(router)
            .node(node_x)
            .node(node_y)
            .build()
        )
        return _assistant(workflow, name="Split")

    @pytest.mark.asyncio
    async def test_content_routes_to_matching_consumer(self):
        assistant = self._content_split_assistant()
        out_x = await _run(assistant, "please do x")
        assert [e.data[0].content for e in out_x] == ["handled by X"]

        assistant = self._content_split_assistant()
        out_y = await _run(assistant, "please do y")
        assert [e.data[0].content for e in out_y] == ["handled by Y"]

    @pytest.mark.asyncio
    async def test_fan_out_to_multiple_consumers(self):
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        to_p = Topic(name="to_p")
        to_q = Topic(name="to_q")

        # default (always) routes -> the one event fans out to BOTH topics
        source = (
            Node.builder()
            .name("Source")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(
                MockTool(fn=lambda _: [Message(role="assistant", content="broadcast")])
            )
            .publish_to(to_p)
            .publish_to(to_q)
            .build()
        )
        node_p = (
            Node.builder()
            .name("P")
            .subscribe(SubscriptionBuilder().subscribed_to(to_p).build())
            .tool(
                MockTool(fn=lambda _: [Message(role="assistant", content="P got it")])
            )
            .publish_to(agent_output)
            .build()
        )
        node_q = (
            Node.builder()
            .name("Q")
            .subscribe(SubscriptionBuilder().subscribed_to(to_q).build())
            .tool(
                MockTool(fn=lambda _: [Message(role="assistant", content="Q got it")])
            )
            .publish_to(agent_output)
            .build()
        )
        workflow = (
            EventDrivenWorkflow.builder()
            .name("fanout")
            .node(source)
            .node(node_p)
            .node(node_q)
            .build()
        )
        out = await _run(_assistant(workflow, name="Fanout"), "go")
        assert sorted(e.data[0].content for e in out) == ["P got it", "Q got it"]

    @pytest.mark.asyncio
    async def test_no_matching_route_drops_event(self):
        agent_input = InputTopic(name="agent_input")
        agent_output = OutputTopic(name="agent_output")
        node = (
            Node.builder()
            .name("Picky")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input).build())
            .tool(MockTool(fn=lambda _: [Message(role="assistant", content="nope")]))
            # only routes a "yes" payload; "nope" matches nothing -> dropped
            .publish_to(agent_output, when=_contains("yes"))
            .build()
        )
        workflow = EventDrivenWorkflow.builder().name("drop").node(node).build()
        out = await _run(_assistant(workflow, name="Drop"), "anything")
        assert out == []  # event matched no route -> no output, no hang
