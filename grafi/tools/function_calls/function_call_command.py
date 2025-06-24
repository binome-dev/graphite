from typing import Any
from typing import Self

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

    def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
        return self.function_call_tool.invoke(invoke_context, input_data)

    async def a_invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        async for message in self.function_call_tool.a_invoke(
            invoke_context, input_data
        ):
            yield message

    def get_function_specs(self) -> FunctionSpecs:
        return self.function_call_tool.get_function_specs()

    def to_dict(self) -> dict[str, Any]:
        return {"function_call_tool": self.function_call_tool.to_dict()}


class FunctionCallCommandBuilder(CommandBuilder[FunctionCallCommand]):
    """Builder for FunctionCallCommand."""

    def function_call_tool(self, function_call_tool: FunctionCallTool) -> Self:
        self._obj.function_call_tool = function_call_tool
        return self

    def build(self) -> FunctionCallCommand:
        if not self._obj.function_call_tool:
            raise ValueError(
                "Function call tool must be set before building the command."
            )
        return self._obj
