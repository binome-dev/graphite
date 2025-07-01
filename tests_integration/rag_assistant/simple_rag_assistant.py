import os
from typing import Optional

from llama_index.core.indices.base import BaseIndex
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import ConfigDict
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.node import Node
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
from tests_integration.rag_assistant.tools.rags.rag_tool import RagTool


class SimpleRagAssistant(Assistant):
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
    name: str = Field(default="SimpleRagAssistant")
    type: str = Field(default="SimpleRagAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: Optional[str] = Field(default="gpt-4o-mini")
    index: BaseIndex

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _construct_workflow(self) -> "SimpleRagAssistant":
        # Create an LLM node
        rag_node = (
            Node.builder()
            .name("RagNode")
            .type("RagNode")
            .subscribe(agent_input_topic)
            .tool(RagTool(name="RagTool", index=self.index))
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the LLM node
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("simple_rag_workflow")
            .node(rag_node)
            .build()
        )

        return self
