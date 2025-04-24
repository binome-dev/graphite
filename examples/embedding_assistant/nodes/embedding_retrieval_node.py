from typing import Any
from typing import List

from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.decorators.record_node_a_execution import record_node_a_execution
from grafi.common.decorators.record_node_execution import record_node_execution
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node

from ..tools.embeddings.embedding_response_command import EmbeddingResponseCommand


class EmbeddingRetrievalNode(Node):
    """Node for interacting with a Retrieval-Augmented Generation (RAG) model."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER
    name: str = "EmbeddingRetrievalNode"
    type: str = "EmbeddingRetrievalNode"
    command: EmbeddingResponseCommand

    class Builder(Node.Builder):
        """Concrete builder for RagNode."""

        _node: "EmbeddingRetrievalNode"

        def _init_node(self) -> "EmbeddingRetrievalNode":
            return EmbeddingRetrievalNode.model_construct()

    @record_node_execution
    def execute(
        self,
        execution_context: ExecutionContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> Messages:
        # Execute the RAG tool with the combined input
        command_input_data = self.get_command_input(node_input)
        return self.command.execute(execution_context, command_input_data)

    @record_node_a_execution
    async def a_execute(
        self,
        execution_context: ExecutionContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        # Execute the RAG tool with the combined input
        command_input_data = self.get_command_input(node_input)
        response = self.command.a_execute(execution_context, command_input_data)

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
