from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List

from grafi.common.decorators.record_decorators import record_node_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.nodes.node_base import NodeBase
from grafi.nodes.node_base import NodeBaseBuilder
from grafi.tools.command import Command
from grafi.tools.tool_factory import ToolFactory
from grafi.topics.expressions.topic_expression import CombinedExpr
from grafi.topics.expressions.topic_expression import TopicExpr
from grafi.topics.expressions.topic_expression import extract_topics
from grafi.topics.topic_base import TopicBase


class Node(NodeBase):
    """Abstract base class for nodes in a graph-based agent system."""

    def model_post_init(self, _context: Any) -> None:
        # Set up the subscribed topics based on the expressions
        topics = {
            topic.name: topic
            for expr in self.subscribed_expressions
            for topic in extract_topics(expr)
        }

        self._subscribed_topics = topics

        # Setup the command if it is not already set
        if self.tool and not self._command:
            self._command = Command.for_tool(self.tool)

    @classmethod
    def builder(cls) -> NodeBaseBuilder:
        """Return a builder for Node."""
        return NodeBaseBuilder(cls)

    @record_node_invoke
    async def invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> AsyncGenerator[PublishToTopicEvent, None]:
        # Use the LLM's invoke method to get the response generator
        async for messages in self.command.invoke(
            invoke_context,
            input_data=node_input,
        ):
            yield PublishToTopicEvent(
                publisher_name=self.name,
                publisher_type=self.type,
                invoke_context=invoke_context,
                consumed_event_ids=[event.event_id for event in node_input],
                data=messages,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
        }

    @classmethod
    async def from_dict(
        cls, node_dict: Dict[str, Any], topics: Dict[str, TopicBase]
    ) -> "Node":
        """Create a Node instance from a dictionary representation."""
        from openinference.semconv.trace import OpenInferenceSpanKindValues

        # Deserialize the tool
        tool = await ToolFactory.from_dict(node_dict["tool"])

        node_builder = (
            Node.builder()
            .name(node_dict["name"])
            .type(node_dict["type"])
            .oi_span_type(
                OpenInferenceSpanKindValues(node_dict.get("oi_span_type", "TOOL"))
            )
            .tool(tool)
        )

        # Deserialize subscribed expressions
        for expr_dict in node_dict["subscribed_expressions"]:
            if "topic" in expr_dict:
                node_builder.subscribe(await TopicExpr.from_dict(expr_dict, topics))
            elif "op" in expr_dict:
                node_builder.subscribe(await CombinedExpr.from_dict(expr_dict, topics))

        for topic_name in node_dict["publish_to"]:
            # Check if topic already exists in topics dict
            if topic_name in topics:
                node_builder.publish_to(topics[topic_name])
            else:
                raise ValueError(f"Unknown topic: {topic_name}")

        return node_builder.build()
