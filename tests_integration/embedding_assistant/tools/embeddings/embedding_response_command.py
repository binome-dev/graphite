from typing import Any

from grafi.common.models.command import Command
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from tests_integration.embedding_assistant.tools.embeddings.retrieval_tool import (
    RetrievalTool,
)


class EmbeddingResponseCommand(Command):
    retrieval_tool: RetrievalTool

    def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Message:
        return self.retrieval_tool.invoke(invoke_context, input_data)

    async def a_invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        async for message in self.retrieval_tool.a_invoke(invoke_context, input_data):
            yield message

    def to_dict(self) -> dict[str, Any]:
        return {"retrieval_tool": self.retrieval_tool.to_dict()}
