from typing import Any, AsyncGenerator, List

from pydantic import Field

from grafi.common.models.command import Command
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.llms.llm import LLM


class LLMResponseCommand(Command):
    llm: LLM = Field(default=None)

    class Builder(Command.Builder):
        """Concrete builder for LLMResponseCommand."""

        def __init__(self):
            self._command = self._init_command()

        def _init_command(self) -> "LLMResponseCommand":
            return LLMResponseCommand()

        def llm(self, llm: LLM) -> "LLMResponseCommand.Builder":
            self._command.llm = llm
            return self

    def execute(
        self, execution_context: ExecutionContext, input_data: List[Message]
    ) -> Message:
        return self.llm.execute(execution_context, input_data)

    async def a_execute(
        self, execution_context: ExecutionContext, input_data: List[Message]
    ) -> AsyncGenerator[Message, None]:
        async for message in self.llm.a_execute(execution_context, input_data):
            yield message

    def to_dict(self) -> dict[str, Any]:
        return {"llm": self.llm.to_dict()}
