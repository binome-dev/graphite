import os
from typing import Optional

from chromadb import Collection
from llama_index.embeddings.openai import OpenAIEmbedding
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import ConfigDict
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.node import Node
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from tests_integration.embedding_assistant.tools.embeddings.impl.chromadb_retrieval_tool import (
    ChromadbRetrievalTool,
)


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

    def _construct_workflow(self) -> "SimpleEmbeddingRetrievalAssistant":
        # Create an LLM node
        embedding_retrieval_node = (
            Node.builder()
            .name("EmbeddingRetrievalNode")
            .type("EmbeddingRetrievalNode")
            .subscribe(agent_input_topic)
            .tool(
                ChromadbRetrievalTool(
                    name="ChromadbRetrievalTool",
                    collection=self.collection,
                    embedding_model=self.embedding_model,
                    n_results=self.n_results,
                )
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the LLM node
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("simple_rag_workflow")
            .node(embedding_retrieval_node)
            .build()
        )

        return self
