from typing import List

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.command import Command
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages


class RagResponseCommand(Command):
    """A command that responds with a message."""

    def get_tool_input(
        self, invoke_context: InvokeContext, node_input: List[ConsumeFromTopicEvent]
    ) -> Messages:
        # Only consider the last message contains the content to query
        latest_event_data = node_input[-1].data
        latest_message = (
            latest_event_data[0]
            if isinstance(latest_event_data, list)
            else latest_event_data
        )
        return [latest_message]
