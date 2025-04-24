from typing import Any
from typing import Self

from examples.rag_assistant.tools.rags.rag_tool import RagTool
from grafi.common.models.command import Command
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen


class RagResponseCommand(Command):
    """A command that responds with a message."""

    rag_tool: RagTool

    class Builder(Command.Builder):
        """Concrete builder for RagResponseCommand."""

        _command: "RagResponseCommand"

        def __init__(self) -> None:
            self._command = self._init_command()

        def _init_command(self) -> "RagResponseCommand":
            return RagResponseCommand.model_construct()

        def rag_tool(self, rag_tool: RagTool) -> Self:
            self._command.rag_tool = rag_tool
            return self

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
