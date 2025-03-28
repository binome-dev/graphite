import json
from typing import AsyncGenerator

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.decorators.record_tool_a_execution import record_tool_a_execution
from grafi.common.decorators.record_tool_execution import record_tool_execution
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message

from ..retrieval_tool import RetrievalTool

try:
    from chromadb import Collection, QueryResult
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
    collection: Collection = Field(default=None)
    embedding_model: OpenAIEmbedding = Field(default=None)
    n_results: int = Field(default=30)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER

    class Builder(RetrievalTool.Builder):
        """Concrete builder for ChromadbRetrievalTool."""

        def __init__(self):
            self._tool = self._init_tool()

        def _init_tool(self) -> "ChromadbRetrievalTool":
            return ChromadbRetrievalTool()

        def embedding_model(
            self, embedding_model: OpenAIEmbedding
        ) -> "ChromadbRetrievalTool.Builder":
            self._tool.embedding_model = embedding_model
            return self

        def n_results(self, n_results: int) -> "ChromadbRetrievalTool.Builder":
            self._tool.n_results = n_results
            return self

        def collection(self, collection: Collection) -> "ChromadbRetrievalTool.Builder":
            self._tool.collection = collection
            return self

    @record_tool_execution
    def execute(self, execution_context: ExecutionContext, input_data: Message):
        embeddings = self.embedding_model._get_text_embeddings(input_data.content)
        result: QueryResult = self.collection.query(
            query_embeddings=embeddings, n_results=self.n_results
        )
        return self.to_message(result)

    @record_tool_a_execution
    async def a_execute(
        self, execution_context: ExecutionContext, input_data: Message
    ) -> AsyncGenerator[Message, None]:
        embeddings = self.embedding_model._get_text_embeddings(input_data.content)
        result: QueryResult = self.collection.query(
            query_embeddings=embeddings, n_results=self.n_results
        )
        yield self.to_message(result)

    def to_message(self, result: QueryResult) -> Message:
        ids = result["ids"][0]
        documents = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]
        response = {
            "ids": ids,
            "documents": documents,
            "metadatas": metadatas,
            "distances": distances,
        }
        content = json.dumps(response)
        return Message(role="assistant", content=content)

    def to_dict(self) -> dict[str, any]:
        return {
            **super().to_dict(),
            "name": self.name,
            "type": self.type,
            "oi_span_type": self.oi_span_type.value,
            "n_results": self.n_results,
            "collection": self.collection.__class__.__name__,
            "embedding_model": self.embedding_model.__class__.__name__,
        }
