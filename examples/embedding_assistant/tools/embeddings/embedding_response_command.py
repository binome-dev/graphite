from typing import Any
from typing import AsyncGenerator

from pydantic import Field

from grafi.common.models.command import Command
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message

from .retrieval_tool import RetrievalTool


class EmbeddingResponseCommand(Command):
    retrieval_tool: RetrievalTool = Field(default=None)

    class Builder(Command.Builder):
        """Concrete builder for EmbeddingResponseCommand."""

        def __init__(self):
            self._command = self._init_command()

        def _init_command(self) -> "EmbeddingResponseCommand":
            return EmbeddingResponseCommand()

        def retrieval_tool(
            self, retrieval_tool: RetrievalTool
        ) -> "EmbeddingResponseCommand.Builder":
            self._command.retrieval_tool = retrieval_tool
            return self

    def execute(
        self, execution_context: ExecutionContext, input_data: Message
    ) -> Message:
        return self.retrieval_tool.execute(execution_context, input_data)

    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Message
    ) -> AsyncGenerator[Message, None]:
        async for message in self.retrieval_tool.a_execute(
            execution_context, input_data
        ):
            yield message

    def to_dict(self) -> dict[str, Any]:
        return {"retrieval_tool": self.retrieval_tool.to_dict()}
