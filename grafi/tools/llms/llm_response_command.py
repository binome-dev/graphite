from typing import Any
from typing import Self

from grafi.common.models.command import Command
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.llms.llm import LLM


class LLMResponseCommand(Command):
    llm: LLM

    class Builder(Command.Builder):
        """Concrete builder for LLMResponseCommand."""

        _command: "LLMResponseCommand"

        def __init__(self) -> None:
            self._command = self._init_command()

        def _init_command(self) -> "LLMResponseCommand":
            return LLMResponseCommand.model_construct()

        def llm(self, llm: LLM) -> Self:
            self._command.llm = llm
            return self

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
