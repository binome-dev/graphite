from typing import Any

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.models.command import use_command
from grafi.tools.tool import Tool
from tests_integration.embedding_assistant.tools.embeddings.embedding_response_command import (
    EmbeddingResponseCommand,
)


@use_command(EmbeddingResponseCommand)
class RetrievalTool(Tool):
    name: str = "RetrievalTool"
    type: str = "RetrievalTool"
    embedding_model: Any = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "oi_span_type": self.oi_span_type.value,
        }
