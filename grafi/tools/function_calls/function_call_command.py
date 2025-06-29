from typing import Any
from typing import List
from typing import Self

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.command import Command
from grafi.common.models.command import CommandBuilder
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.function_calls.function_call_tool import FunctionCallTool


class FunctionCallCommand(Command):
    """A command that calls a function on the context object."""

    function_call_tool: FunctionCallTool

    @classmethod
    def builder(cls) -> "FunctionCallCommandBuilder":
        """Return a builder for FunctionCallCommand."""
        return FunctionCallCommandBuilder(cls)

    def invoke(
        self, invoke_context: InvokeContext, input_data: List[ConsumeFromTopicEvent]
    ) -> Messages:
        return self.function_call_tool.invoke(
            invoke_context, self.get_tool_input(input_data)
        )

    async def a_invoke(
        self, invoke_context: InvokeContext, input_data: List[ConsumeFromTopicEvent]
    ) -> MsgsAGen:
        async for message in self.function_call_tool.a_invoke(
            invoke_context, self.get_tool_input(input_data)
        ):
            yield message

    def get_tool_input(self, node_input: List[ConsumeFromTopicEvent]) -> Messages:
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

    def get_function_specs(self) -> FunctionSpecs:
        return self.function_call_tool.get_function_specs()

    def to_dict(self) -> dict[str, Any]:
        return {"function_call_tool": self.function_call_tool.to_dict()}


class FunctionCallCommandBuilder(CommandBuilder[FunctionCallCommand]):
    """Builder for FunctionCallCommand."""

    def function_call_tool(self, function_call_tool: FunctionCallTool) -> Self:
        self.kwargs["function_call_tool"] = function_call_tool
        return self
