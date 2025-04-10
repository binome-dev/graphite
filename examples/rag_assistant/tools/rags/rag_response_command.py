from typing import Any
from typing import AsyncGenerator

from pydantic import Field

from grafi.common.models.command import Command
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message

from .rag_tool import RagTool


class RagResponseCommand(Command):
    """A command that responds with a message."""

    rag_tool: RagTool = Field(default=None)

    class Builder(Command.Builder):
        """Concrete builder for RagResponseCommand."""

        def __init__(self):
            self._command = self._init_command()

        def _init_command(self) -> "RagResponseCommand":
            return RagResponseCommand()

        def rag_tool(self, rag_tool: RagTool) -> "RagResponseCommand.Builder":
            self._command.rag_tool = rag_tool
            return self

    def execute(
        self, execution_context: ExecutionContext, input_data: Message
    ) -> Message:
        return self.rag_tool.execute(execution_context, input_data)

    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Message
    ) -> AsyncGenerator[Message, None]:
        async for message in self.rag_tool.a_execute(execution_context, input_data):
            yield message

    def to_dict(self) -> dict[str, Any]:
        return {"rag_tool": self.rag_tool.to_dict()}
