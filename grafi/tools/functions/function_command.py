from typing import Any
from typing import Self

from grafi.common.models.command import Command
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.functions.function_tool import FunctionTool


class FunctionCommand(Command):
    function_tool: FunctionTool

    class Builder(Command.Builder):
        """Concrete builder for EmbeddingResponseCommand."""

        _command: "FunctionCommand"

        def __init__(self) -> None:
            self._command = self._init_command()

        def _init_command(self) -> "FunctionCommand":
            return FunctionCommand.model_construct()

        def function_tool(self, function_tool: FunctionTool) -> Self:
            self._command.function_tool = function_tool
            return self

    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Message:
        return self.function_tool.execute(execution_context, input_data)

    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> MsgsAGen:
        async for message in self.function_tool.a_execute(
            execution_context, input_data
        ):
            yield message

    def to_dict(self) -> dict[str, Any]:
        return {"function_tool": self.function_tool.to_dict()}
