from typing import Any

from grafi.common.models.command import Command
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from tests_integration.embedding_assistant.tools.embeddings.retrieval_tool import (
    RetrievalTool,
)


class EmbeddingResponseCommand(Command):
    retrieval_tool: RetrievalTool

    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Message:
        return self.retrieval_tool.execute(execution_context, input_data)

    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> MsgsAGen:
        async for message in self.retrieval_tool.a_execute(
            execution_context, input_data
        ):
            yield message

    def to_dict(self) -> dict[str, Any]:
        return {"retrieval_tool": self.retrieval_tool.to_dict()}
