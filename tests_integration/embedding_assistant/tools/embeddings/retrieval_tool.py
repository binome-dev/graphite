from typing import Any

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.tools.command import use_command
from grafi.tools.tool import Tool
from tests_integration.embedding_assistant.tools.embeddings.embedding_response_command import (
    EmbeddingResponseCommand,
)


@use_command(EmbeddingResponseCommand)
class RetrievalTool(Tool):
    name: str = "RetrievalTool"
    type: str = "RetrievalTool"
    # A live client, not data: left out of the tool's manifest.
    embedding_model: Any = Field(default=None, exclude=True)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER
