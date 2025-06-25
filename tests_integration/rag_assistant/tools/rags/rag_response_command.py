from typing import Any

from grafi.common.models.command import Command
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from tests_integration.rag_assistant.tools.rags.rag_tool import RagTool


class RagResponseCommand(Command):
    """A command that responds with a message."""

    rag_tool: RagTool

    def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
        return self.rag_tool.invoke(invoke_context, input_data)

    async def a_invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        async for message in self.rag_tool.a_invoke(invoke_context, input_data):
            yield message

    def to_dict(self) -> dict[str, Any]:
        return {"rag_tool": self.rag_tool.to_dict()}
