from typing import Any
from typing import Self

from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.llms.llm import LLM
from grafi.tools.llms.llm_response_command import LLMResponseCommand


class LLMStreamResponseCommand(LLMResponseCommand):
    llm: LLM

    class Builder(LLMResponseCommand.Builder):
        """Concrete builder for LLMResponseCommand."""

        def __init__(self) -> None:
            self._command = self._init_command()

        def _init_command(self) -> "LLMStreamResponseCommand":
            return LLMStreamResponseCommand.model_construct()

        def llm(self, llm: LLM) -> Self:
            self._command.llm = llm
            return self

    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Message:
        raise NotImplementedError("Method 'execute' not implemented in stream command")

    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> MsgsAGen:

        async for message in self.llm.a_stream(execution_context, input_data):
            yield message

    def to_dict(self) -> dict[str, Any]:
        return {"llm": self.llm.to_dict()}
