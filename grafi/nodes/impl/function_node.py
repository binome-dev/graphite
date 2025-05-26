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
from grafi.tools.functions.function_command import FunctionCommand


class FunctionNode(Node):
    """Node for interacting with a Retrieval-Augmented Generation (RAG) model."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER
    name: str = "FunctionNode"
    type: str = "FunctionNode"
    command: FunctionCommand

    class Builder(Node.Builder):
        """Concrete builder for RagNode."""

        _node: "FunctionNode"

        def _init_node(self) -> "FunctionNode":
            return FunctionNode.model_construct()

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
        all_messages = []
        for event in node_input:
            all_messages.extend(event.data)
        return all_messages

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "oi_span_type": self.oi_span_type.value,
            "name": self.name,
            "type": self.type,
            "command": self.command.to_dict(),
        }
