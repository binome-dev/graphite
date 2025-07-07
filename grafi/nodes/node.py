from typing import Any
from typing import List

from loguru import logger

from grafi.common.decorators.record_node_a_invoke import record_node_a_invoke
from grafi.common.decorators.record_node_invoke import record_node_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.command import Command
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.common.topics.topic_expression import evaluate_subscription
from grafi.common.topics.topic_expression import extract_topics
from grafi.nodes.node_base import NodeBase
from grafi.nodes.node_base import NodeBaseBuilder


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
    def invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> Messages:
        logger.debug(f"Executing Node with inputs: {node_input}")

        # Use the LLM's invoke method to get the response
        response = self.command.invoke(
            invoke_context,
            node_input,
        )

        # Handle the response and update the output
        return response

    @record_node_a_invoke
    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        logger.debug(f"Executing Node with inputs: {node_input}")

        # Use the LLM's invoke method to get the response generator
        async for messages in self.command.a_invoke(
            invoke_context,
            input_data=node_input,
        ):
            yield messages

    def can_invoke(self) -> bool:
        """
        Check if this node can invoke given which topics currently have new data.
        If ALL of the node's subscribed_expressions is True, we return True.
        :return: Boolean indicating whether the node should run.
        """
        if not self.subscribed_expressions:
            return True

        topics_with_new_msgs = set()

        # Evaluate each expression; if any is satisfied, we can invoke.
        for topic in self._subscribed_topics.values():
            if topic.can_consume(self.name):
                topics_with_new_msgs.add(topic.name)

        for expr in self.subscribed_expressions:
            if not evaluate_subscription(expr, list(topics_with_new_msgs)):
                return False

        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
        }
