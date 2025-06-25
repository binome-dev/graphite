from typing import Any
from typing import Self

from grafi.common.models.command import Command
from grafi.common.models.command import CommandBuilder
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.functions.function_tool import FunctionTool


class FunctionCommand(Command):
    function_tool: FunctionTool

    @classmethod
    def builder(cls) -> "FunctionCommandBuilder":
        """
        Return a builder for FunctionCommand.

        This method allows for the construction of a FunctionCommand instance with specified parameters.
        """
        return FunctionCommandBuilder(cls)

    def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Message:
        return self.function_tool.invoke(invoke_context, input_data)

    async def a_invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        async for message in self.function_tool.a_invoke(invoke_context, input_data):
            yield message

    def to_dict(self) -> dict[str, Any]:
        return {"function_tool": self.function_tool.to_dict()}


class FunctionCommandBuilder(CommandBuilder[FunctionCommand]):
    """
    Builder for FunctionCommand.
    """

    def function_tool(self, function_tool: FunctionTool) -> Self:
        self._obj.function_tool = function_tool
        return self

    def build(self) -> FunctionCommand:
        return self._obj
