from typing import Any
from typing import Self

from grafi.common.models.command import Command
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.function_calls.function_call_tool import FunctionCallTool


class FunctionCallCommand(Command):
    """A command that calls a function on the context object."""

    function_tool: FunctionCallTool

    class Builder(Command.Builder):
        """Concrete builder for FunctionCallCommand."""

        _command: "FunctionCallCommand"

        def __init__(self) -> None:
            self._command = self._init_command()

        def _init_command(self) -> "FunctionCallCommand":
            return FunctionCallCommand.model_construct()

        def function_tool(self, function_tool: FunctionCallTool) -> Self:
            self._command.function_tool = function_tool
            return self

    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Messages:
        return self.function_tool.execute(execution_context, input_data)

    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> MsgsAGen:
        async for message in self.function_tool.a_execute(
            execution_context, input_data
        ):
            yield message

    def get_function_specs(self) -> FunctionSpecs:
        return self.function_tool.get_function_specs()

    def to_dict(self) -> dict[str, Any]:
        return {"function_tool": self.function_tool.to_dict()}
