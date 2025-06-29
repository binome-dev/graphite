from typing import Any
from typing import List

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.command import Command
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from tests_integration.rag_assistant.tools.rags.rag_tool import RagTool


class RagResponseCommand(Command):
    """A command that responds with a message."""

    rag_tool: RagTool

    def invoke(
        self, invoke_context: InvokeContext, input_data: List[ConsumeFromTopicEvent]
    ) -> Messages:
        return self.rag_tool.invoke(invoke_context, self.get_tool_input(input_data))

    async def a_invoke(
        self, invoke_context: InvokeContext, input_data: List[ConsumeFromTopicEvent]
    ) -> MsgsAGen:
        async for message in self.rag_tool.a_invoke(
            invoke_context, self.get_tool_input(input_data)
        ):
            yield message

    def get_tool_input(self, node_input: List[ConsumeFromTopicEvent]) -> Messages:
        # Only consider the last message contains the content to query
        latest_event_data = node_input[-1].data
        latest_message = (
            latest_event_data[0]
            if isinstance(latest_event_data, list)
            else latest_event_data
        )
        return [latest_message]

    def to_dict(self) -> dict[str, Any]:
        return {"rag_tool": self.rag_tool.to_dict()}
