from typing import Any
from typing import Self

from grafi.common.models.command import Command
from grafi.common.models.command import CommandBuilder
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.llms.llm import LLM


class LLMResponseCommand(Command):
    llm: LLM

    @classmethod
    def builder(cls) -> "LLMResponseCommandBuilder":
        """
        Return a builder for LLMResponseCommand.

        This method allows for the construction of an LLMResponseCommand instance with specified parameters.
        """
        return LLMResponseCommandBuilder(cls)

    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Messages:
        return self.llm.execute(execution_context, input_data)

    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> MsgsAGen:
        async for messages in self.llm.a_execute(execution_context, input_data):
            yield messages

    def to_dict(self) -> dict[str, Any]:
        return {"llm": self.llm.to_dict()}


class LLMResponseCommandBuilder(CommandBuilder[LLMResponseCommand]):
    """
    Builder for LLMResponseCommand.
    """

    def llm(self, llm: LLM) -> Self:
        self._obj.llm = llm
        return self

    def build(self) -> LLMResponseCommand:
        return self._obj
