from typing import Any

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.tools.tool import Tool


class RetrievalTool(Tool):
    name: str = "RetrievalTool"
    type: str = "RetrievalTool"
    embedding_model: Any = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER

    class Builder(Tool.Builder):
        """Concrete builder for retrieval tool."""

        def __init__(self):
            self._tool = self._init_tool()

        def _init_tool(self) -> "RetrievalTool":
            return RetrievalTool()

        def embedding_model(self, embedding_model: Any) -> "RetrievalTool.Builder":
            self._tool.embedding_model = embedding_model
            return self

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "oi_span_type": self.oi_span_type.value,
        }
