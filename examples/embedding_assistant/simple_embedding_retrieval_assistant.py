import os
from typing import Optional
from typing import Self

from chromadb import Collection
from llama_index.embeddings.openai import OpenAIEmbedding
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import ConfigDict
from pydantic import Field

from examples.embedding_assistant.nodes.embedding_retrieval_node import (
    EmbeddingRetrievalNode,
)
from examples.embedding_assistant.tools.embeddings.embedding_response_command import (
    EmbeddingResponseCommand,
)
from examples.embedding_assistant.tools.embeddings.impl.chromadb_retrieval_tool import (
    ChromadbRetrievalTool,
)
from grafi.assistants.assistant import Assistant
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class SimpleEmbeddingRetrievalAssistant(Assistant):
    """
    A simple assistant class that uses OpenAI's language model and RAG to process input and generate responses.

    This class sets up a workflow with a single RAG node using OpenAI's API, and provides a method
    to run input through this workflow.

    Attributes:
        api_key (str): The API key for OpenAI. If not provided, it tries to use the OPENAI_API_KEY environment variable.
        model (str): The name of the OpenAI model to use.
        event_store (EventStore): An instance of EventStore to record events during the assistant's operation.
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="SimpleEmbeddingRetrievalAssistant")
    type: str = Field(default="SimpleEmbeddingRetrievalAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    embedding_model: Optional[OpenAIEmbedding] = Field(default=None)
    n_results: int = Field(default=30)

    collection: Collection

    model_config = ConfigDict(arbitrary_types_allowed=True)

    class Builder(Assistant.Builder):
        """Concrete builder for WorkflowDag."""

        _assistant: "SimpleEmbeddingRetrievalAssistant"

        def __init__(self) -> None:
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "SimpleEmbeddingRetrievalAssistant":
            return SimpleEmbeddingRetrievalAssistant.model_construct()

        def api_key(self, api_key: str) -> Self:
            self._assistant.api_key = api_key
            return self

        def embedding_model(self, embedding_model: OpenAIEmbedding) -> Self:
            self._assistant.embedding_model = embedding_model
            return self

        def n_results(self, n_results: int) -> Self:
            self._assistant.n_results = n_results
            return self

        def collection(self, collection: Collection) -> Self:
            self._assistant.collection = collection
            return self

        def build(self) -> "SimpleEmbeddingRetrievalAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "SimpleEmbeddingRetrievalAssistant":
        # Create an LLM node
        embedding_retrieval_node = (
            EmbeddingRetrievalNode.Builder()
            .name("EmbeddingRetrievalNode")
            .subscribe(agent_input_topic)
            .command(
                EmbeddingResponseCommand.Builder()
                .retrieval_tool(
                    ChromadbRetrievalTool.Builder()
                    .collection(self.collection)
                    .embedding_model(self.embedding_model)
                    .n_results(self.n_results)
                    .build()
                )
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the LLM node
        self.workflow = (
            EventDrivenWorkflow.Builder()
            .name("simple_rag_workflow")
            .node(embedding_retrieval_node)
            .build()
        )

        return self
