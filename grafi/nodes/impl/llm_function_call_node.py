from typing import Any
from typing import List

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.decorators.record_node_a_execution import record_node_a_execution
from grafi.common.decorators.record_node_execution import record_node_execution
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_command import FunctionCallCommand


class LLMFunctionCallNode(Node):
    """Node for making a function call using a Language Model (LLM)."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.CHAIN
    name: str = "LLMFunctionCallNode"
    type: str = "LLMFunctionCallNode"
    command: FunctionCallCommand

    class Builder(Node.Builder):
        """Concrete builder for LLMFunctionCallNode."""

        _node: "LLMFunctionCallNode"

        def _init_node(self) -> "LLMFunctionCallNode":
            return LLMFunctionCallNode.model_construct()

    @record_node_execution
    def execute(
        self,
        execution_context: ExecutionContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> Messages:
        # Parse the LLM response to extract function call details

        tool_response_messages = []
        command_input = self.get_command_input(node_input)
        for tool_call_message in command_input:
            # Execute the function using the tool (Function class)
            function_response_message = self.command.execute(
                execution_context, [tool_call_message]
            )

            if len(function_response_message) > 0:
                tool_response_messages.extend(function_response_message)

        # Set the output messages
        return tool_response_messages

    @record_node_a_execution
    async def a_execute(
        self,
        execution_context: ExecutionContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        # Parse the LLM response to extract function call details

        try:
            command_input = self.get_command_input(node_input)

            # Execute all function calls concurrently
            for message in command_input:
                async for function_response_message in self.command.a_execute(
                    execution_context, [message]
                ):
                    yield function_response_message

        except Exception as e:
            logger.error(f"Error in async function execution: {str(e)}")
            raise

    def get_function_specs(self) -> FunctionSpecs:
        return self.command.get_function_specs()

    def get_command_input(self, node_input: List[ConsumeFromTopicEvent]) -> Messages:
        tool_calls_messages = []

        # Only process messages in root event nodes, which is the current node directly consumed by the workflow
        input_messages = [
            msg
            for event in node_input
            for msg in (event.data if isinstance(event.data, list) else [event.data])
        ]

        # Filter messages with unprocessed tool calls
        proceed_tool_calls = [
            msg.tool_call_id for msg in input_messages if msg.tool_call_id
        ]
        for message in input_messages:
            if (
                message.tool_calls
                and message.tool_calls[0].id not in proceed_tool_calls
            ):
                tool_calls_messages.append(message)

        return tool_calls_messages

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "oi_span_type": self.oi_span_type.value,
            "name": self.name,
            "type": self.type,
            "command": self.command.to_dict(),
        }
