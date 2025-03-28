from typing import Any, AsyncGenerator, List

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from examples.rag_assistant.tools.rags.rag_response_command import RagResponseCommand
from grafi.common.decorators.record_node_a_execution import record_node_a_execution
from grafi.common.decorators.record_node_execution import record_node_execution
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node


class RagNode(Node):
    """Node for interacting with a Retrieval-Augmented Generation (RAG) model."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER
    name: str = "RagNode"
    type: str = "RagNode"
    command: RagResponseCommand = Field(default=None)

    class Builder(Node.Builder):
        """Concrete builder for RagNode."""

        def _init_node(self) -> "RagNode":
            return RagNode()

    @record_node_execution
    def execute(
        self,
        execution_context: ExecutionContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> List[Message]:
        # Execute the RAG tool with the combined input
        command_input_data = self.get_command_input(node_input)
        response = [self.command.execute(execution_context, command_input_data)]

        # Set the output Message
        return response

    @record_node_a_execution
    async def a_execute(
        self,
        execution_context: ExecutionContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> AsyncGenerator[Message, None]:
        # Execute the RAG tool with the combined input
        command_input_data = self.get_command_input(node_input)
        response = self.command.a_execute(execution_context, command_input_data)

        # Set the output Message
        async for message in response:
            yield message

    def get_command_input(self, node_input: List[ConsumeFromTopicEvent]) -> Message:
        # Only consider the last message contains the content to query
        latest_event_data = node_input[-1].data
        latest_message = (
            latest_event_data[0]
            if isinstance(latest_event_data, list)
            else latest_event_data
        )
        return latest_message

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "oi_span_type": self.oi_span_type.value,
            "name": self.name,
            "type": self.type,
            "command": self.command.to_dict(),
        }
