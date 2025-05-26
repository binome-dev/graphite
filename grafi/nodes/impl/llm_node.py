"""Module for LLM-related node implementations."""

from typing import Any
from typing import List

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.containers.container import container
from grafi.common.decorators.record_node_a_execution import record_node_a_execution
from grafi.common.decorators.record_node_execution import record_node_execution
from grafi.common.events.assistant_events.assistant_respond_event import (
    AssistantRespondEvent,
)
from grafi.common.events.event_graph import EventGraph
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.nodes.node import Node
from grafi.tools.llms.llm_response_command import LLMResponseCommand


class LLMNode(Node):
    """Node for interacting with a Language Model (LLM)."""

    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.CHAIN
    name: str = "LLMNode"
    type: str = "LLMNode"
    command: LLMResponseCommand
    function_specs: FunctionSpecs = Field(default=[])

    class Builder(Node.Builder):
        """Concrete builder for LLMNode."""

        _node: "LLMNode"

        def _init_node(self) -> "LLMNode":
            return LLMNode.model_construct()

    def add_function_spec(self, function_spec: FunctionSpecs) -> None:
        """Add a function specification to the node."""
        self.function_specs.extend(function_spec)

    @record_node_execution
    def execute(
        self,
        execution_context: ExecutionContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> Messages:
        logger.debug(f"Executing LLMNode with inputs: {node_input}")

        # Use the LLM's execute method to get the response
        response = self.command.execute(
            execution_context,
            input_data=self.get_command_input(execution_context, node_input),
        )

        # Handle the response and update the output
        return response

    @record_node_a_execution
    async def a_execute(
        self,
        execution_context: ExecutionContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> MsgsAGen:
        logger.debug(f"Executing LLMNode with inputs: {node_input}")

        # Use the LLM's execute method to get the response generator
        async for messages in self.command.a_execute(
            execution_context,
            input_data=self.get_command_input(execution_context, node_input),
        ):
            yield messages

    def get_command_input(
        self,
        execution_context: ExecutionContext,
        node_input: List[ConsumeFromTopicEvent],
    ) -> Messages:
        """Prepare the input for the LLM command based on the node input and execution context."""

        # Get conversation history messages from the event store

        conversation_events = container.event_store.get_conversation_events(
            execution_context.conversation_id
        )

        assistant_respond_event_dict = {
            event.event_id: event
            for event in conversation_events
            if isinstance(event, AssistantRespondEvent)
        }

        # Get all the input and output message from assistant respond events as list
        all_messages: Messages = []
        for event in assistant_respond_event_dict.values():
            if (
                event.execution_context.assistant_request_id
                != execution_context.assistant_request_id
            ):
                all_messages.extend(event.input_data)
                all_messages.extend(event.output_data)

        # Sort the messages by timestamp
        sorted_messages: Messages = sorted(
            all_messages, key=lambda item: item.timestamp
        )

        # Retrieve agent events related to the current assistant request
        agent_events = container.event_store.get_agent_events(
            execution_context.assistant_request_id
        )
        topic_events = {
            event.event_id: event
            for event in agent_events
            if isinstance(event, ConsumeFromTopicEvent)
            or isinstance(event, PublishToTopicEvent)
        }
        event_graph = EventGraph()
        event_graph.build_graph(node_input, topic_events)

        node_input_events = [
            event_node.event for event_node in event_graph.get_topology_sorted_events()
        ]

        messages: Messages = [msg for event in node_input_events for msg in event.data]

        # Make sure the llm tool call message are followed by the function call messages
        # Step 1: get all the messages with tool_call_id and remove them from the messages list
        tool_call_messages = {
            msg.tool_call_id: msg for msg in messages if msg.tool_call_id is not None
        }
        messages = [msg for msg in messages if msg.tool_call_id is None]

        # Step 2: loop over the messages again, find the llm messages with tool_calls, and append corresponding the tool_call_messages
        i = 0
        while i < len(messages):
            message = messages[i]
            if message.tool_calls is not None:
                for tool_call in message.tool_calls:
                    if tool_call.id in tool_call_messages:
                        messages.insert(i + 1, tool_call_messages[tool_call.id])
                    else:
                        logger.warning(
                            f"Tool call message not found for id: {tool_call.id}, add an empty message"
                        )
                        message_args = {
                            "role": "tool",
                            "content": None,
                            "tool_call_id": tool_call.id,
                        }
                        messages.insert(i + 1, Message.model_validate(message_args))
                i += len(message.tool_calls) + 1
            else:
                i += 1

        # Attach function specs to the last message
        if self.function_specs and messages:
            last_message = messages[-1]
            last_message.tools = [spec.to_openai_tool() for spec in self.function_specs]

        sorted_messages.extend(messages)

        return sorted_messages

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "oi_span_type": self.oi_span_type.value,
            "name": self.name,
            "type": self.type,
            "command": self.command.to_dict(),
            "function_specs": [spec.model_dump() for spec in self.function_specs],
        }
