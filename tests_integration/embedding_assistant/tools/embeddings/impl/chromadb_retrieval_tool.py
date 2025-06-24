import json
from typing import Any

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.decorators.record_tool_a_invoke import record_tool_a_invoke
from grafi.common.decorators.record_tool_invoke import record_tool_invoke
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen
from tests_integration.embedding_assistant.tools.embeddings.retrieval_tool import (
    RetrievalTool,
)


try:
    from chromadb import Collection
    from chromadb import QueryResult
except ImportError:
    raise ImportError(
        "`chromadb` not installed. Please install using `pip install chromadb`"
    )

try:
    from llama_index.embeddings.openai import OpenAIEmbedding
except ImportError:
    raise ImportError(
        "`llama_index` not installed. Please install using `pip install llama-index-llms-openai llama-index-embeddings-openai`"
    )


class ChromadbRetrievalTool(RetrievalTool):
    name: str = "ChromadbRetrievalTool"
    type: str = "ChromadbRetrievalTool"
    collection: Collection
    embedding_model: OpenAIEmbedding
    n_results: int = Field(default=30)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER

    @record_tool_invoke
    def invoke(self, invoke_context: InvokeContext, input_data: Messages) -> Messages:
        embeddings = self.embedding_model._get_text_embeddings(input_data[-1].content)
        result: QueryResult = self.collection.query(
            query_embeddings=embeddings, n_results=self.n_results
        )
        return self.to_messages(result)

    @record_tool_a_invoke
    async def a_invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> MsgsAGen:
        embeddings = self.embedding_model._get_text_embeddings(input_data[-1].content)
        result: QueryResult = self.collection.query(
            query_embeddings=embeddings, n_results=self.n_results
        )
        yield self.to_messages(result)

    def to_messages(self, result: QueryResult) -> Messages:
        ids = result["ids"]
        documents = result["documents"]
        metadatas = result["metadatas"]
        distances = result["distances"]
        response = {
            "ids": ids,
            "documents": documents,
            "metadatas": metadatas,
            "distances": distances,
        }
        content = json.dumps(response)
        return [Message(role="assistant", content=content)]

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "oi_span_type": self.oi_span_type.value,
            "n_results": self.n_results,
            "collection": self.collection.__class__.__name__,
            "embedding_model": self.embedding_model.__class__.__name__,
        }
