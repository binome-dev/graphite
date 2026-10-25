import json
from typing import Optional

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.decorators.record_decorators import record_tool_invoke
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
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
    # A live collection and client, not data: left out of the tool's manifest,
    # so given again to a tool loaded from one.
    collection: Optional[Collection] = Field(default=None, exclude=True)
    embedding_model: Optional[OpenAIEmbedding] = Field(default=None, exclude=True)
    n_results: int = Field(default=30)
    oi_span_type: OpenInferenceSpanKindValues = OpenInferenceSpanKindValues.RETRIEVER

    @record_tool_invoke
    async def invoke(
        self, invoke_context: InvokeContext, input_data: Messages
    ) -> Messages:
        if self.collection is None or self.embedding_model is None:
            raise ValueError(f"{self.name} has no collection or embedding model.")
        embeddings = self.embedding_model._get_text_embeddings(input_data[-1].content)
        result: QueryResult = self.collection.query(
            query_embeddings=embeddings, n_results=self.n_results
        )
        return self.to_messages(result)

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
