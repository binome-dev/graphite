from typing import Any
from typing import List

from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.decorators.record_node_a_invoke import record_node_a_invoke
from grafi.common.decorators.record_node_invoke import record_node_invoke
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.nodes.node import NodeBuilder

from ..tools.embeddings.embedding_response_command import EmbeddingResponseCommand


class EmbeddingRetrievalNode(Node):
    """Node for interacting with a Retrieval-Augmented Generation (RAG) model."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER
    name: str = "EmbeddingRetrievalNode"
    type: str = "EmbeddingRetrievalNode"
    command: EmbeddingResponseCommand

    @classmethod
    def builder(cls) -> NodeBuilder:
        """Return a builder for EmbeddingRetrievalNode."""
        return NodeBuilder(cls)

    @record_node_invoke
    def invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> Messages:
        # Invoke the RAG tool with the combined input
        command_input_data = self.get_command_input(node_input)
        return self.command.invoke(invoke_context, command_input_data)

    @record_node_a_invoke
    async def a_invoke(
        self,
        invoke_context: InvokeContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        # Invoke the RAG tool with the combined input
        command_input_data = self.get_command_input(node_input)
        response = self.command.a_invoke(invoke_context, command_input_data)

        # Set the output Message
        async for message in response:
            yield message

    def get_command_input(self, node_input: List[ConsumeFromTopicEvent]) -> Messages:
        # Only consider the last message contains the content to query
        latest_event_data = node_input[-1].data
        latest_message = (
            latest_event_data[0]
            if isinstance(latest_event_data, list)
            else latest_event_data
        )
        return [latest_message]

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "oi_span_type": self.oi_span_type.value,
            "name": self.name,
            "type": self.type,
            "command": self.command.to_dict(),
        }
