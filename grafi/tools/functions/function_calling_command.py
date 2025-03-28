from typing import Any, AsyncGenerator, List

from pydantic import Field

from grafi.common.models.command import Command
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.functions.function_tool import FunctionTool


class FunctionCallingCommand(Command):
    """A command that calls a function on the context object."""

    function_tool: FunctionTool = Field(default=None)

    class Builder(Command.Builder):
        """Concrete builder for FunctionCallingCommand."""

        def __init__(self):
            self._command = self._init_command()

        def _init_command(self) -> "FunctionCallingCommand":
            return FunctionCallingCommand()

        def function_tool(
            self, function_tool: FunctionTool
        ) -> "FunctionCallingCommand.Builder":
            self._command.function_tool = function_tool
            return self

    def execute(
        self, execution_context: ExecutionContext, input_data: Message
    ) -> List[Message]:
        return self.function_tool.execute(execution_context, input_data)

    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Message
    ) -> AsyncGenerator[Message, None]:
        async for message in self.function_tool.a_execute(
            execution_context, input_data
        ):
            yield message

    def get_function_specs(self):
        return self.function_tool.get_function_specs()

    def to_dict(self) -> dict[str, Any]:
        return {"function_tool": self.function_tool.to_dict()}
