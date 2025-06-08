from typing import Any

from examples.rag_assistant.tools.rags.rag_tool import RagTool
from grafi.common.models.command import Command
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen


class RagResponseCommand(Command):
    """A command that responds with a message."""

    rag_tool: RagTool

    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Messages:
        return self.rag_tool.execute(execution_context, input_data)

    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> MsgsAGen:
        async for message in self.rag_tool.a_execute(execution_context, input_data):
            yield message

    def to_dict(self) -> dict[str, Any]:
        return {"rag_tool": self.rag_tool.to_dict()}
