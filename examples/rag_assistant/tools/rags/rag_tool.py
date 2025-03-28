from typing import Any, AsyncGenerator, Dict

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.tools.tool import Tool

try:
    from llama_index.core.base.response.schema import RESPONSE_TYPE
    from llama_index.core.indices.base import BaseIndex
except ImportError:
    raise ImportError(
        "`llama_index` not installed. Please install using `pip install llama-index-core`"
    )


class RagTool(Tool):
    name: str = "RagTool"
    type: str = "RagTool"
    index: BaseIndex = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER

    class Builder(Tool.Builder):
        """Concrete builder for WorkflowDag."""

        def __init__(self):
            self._tool = self._init_tool()

        def _init_tool(self) -> "RagTool":
            return RagTool()

        def index(self, index: BaseIndex) -> "RagTool.Builder":
            self._tool.index = index
            return self

    @record_tool_execution
    def execute(
        self, execution_context: ExecutionContext, input_data: Message
    ) -> Message:
        query_engine = self.index.as_query_engine()
        response = query_engine.query(input_data.content)
        return self.to_message(response)

    @record_tool_a_execution
    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Message
    ) -> AsyncGenerator[Message, None]:
        query_engine = self.index.as_query_engine(use_async=True)
        response = await query_engine.aquery(input_data.content)
        yield self.to_message(response)

    def to_message(self, response: RESPONSE_TYPE) -> Message:
        return Message(role="assistant", content=response.response)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "text": self.type,
            "oi_span_type": self.oi_span_type.value,
            "index": self.index.__class__.__name__,
        }
