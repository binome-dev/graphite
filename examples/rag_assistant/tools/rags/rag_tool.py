from typing import Any
from typing import Dict
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues

from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from grafi.tools.tool import Tool


try:
    from llama_index.core.base.response.schema import RESPONSE_TYPE
    from llama_index.core.base.response.schema import PydanticResponse
    from llama_index.core.base.response.schema import Response
    from llama_index.core.indices.base import BaseIndex
except ImportError:
    raise ImportError(
        "`llama_index` not installed. Please install using `pip install llama-index-core`"
    )


class RagTool(Tool):
    name: str = "RagTool"
    type: str = "RagTool"
    index: BaseIndex
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER

    class Builder(Tool.Builder):
        """Concrete builder for WorkflowDag."""

        _tool: "RagTool"

        def __init__(self) -> None:
            self._tool = self._init_tool()

        def _init_tool(self) -> "RagTool":
            return RagTool.model_construct()

        def index(self, index: BaseIndex) -> Self:
            self._tool.index = index
            return self

        def build(self) -> "RagTool":
            return self._tool

    @record_tool_execution
    def execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> Messages:
        query_engine = self.index.as_query_engine()
        response = query_engine.query(input_data[-1].content)
        return self.to_messages(response)

    @record_tool_a_execution
    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Messages
    ) -> MsgsAGen:
        query_engine = self.index.as_query_engine(use_async=True)
        response = await query_engine.aquery(input_data[-1].content)
        yield self.to_messages(response)

    def to_messages(self, response: RESPONSE_TYPE) -> Messages:
        if isinstance(response, Response) or isinstance(response, PydanticResponse):
            return [Message(role="assistant", content=str(response.response))]
        else:
            return [Message(role="assistant", content=str(response))]

    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "text": self.type,
            "oi_span_type": self.oi_span_type.value,
            "index": self.index.__class__.__name__,
        }
