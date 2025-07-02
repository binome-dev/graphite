from typing import List

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.command import Command
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages


class FunctionCallCommand(Command):
    """A command that calls a function on the context object."""

    def get_tool_input(
        self, _: InvokeContext, node_input: List[ConsumeFromTopicEvent]
    ) -> Messages:
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
