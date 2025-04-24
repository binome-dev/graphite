import os
from typing import Optional
from typing import Self

from llama_index.core.indices.base import BaseIndex
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import ConfigDict
from pydantic import Field

from examples.rag_assistant.nodes.rag_node import RagNode
from examples.rag_assistant.tools.rags.rag_response_command import RagResponseCommand
from examples.rag_assistant.tools.rags.rag_tool import RagTool
from grafi.assistants.assistant import Assistant
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


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

    class Builder(Assistant.Builder):
        """Concrete builder for WorkflowDag."""

        _assistant: "SimpleRagAssistant"

        def __init__(self) -> None:
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "SimpleRagAssistant":
            return SimpleRagAssistant.model_construct()

        def api_key(self, api_key: str) -> Self:
            self._assistant.api_key = api_key
            return self

        def model(self, model: str) -> Self:
            self._assistant.model = model
            return self

        def index(self, index: BaseIndex) -> Self:
            self._assistant.index = index
            return self

        def build(self) -> "SimpleRagAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "SimpleRagAssistant":
        # Create an LLM node
        rag_node = (
            RagNode.Builder()
            .name("RagNode")
            .subscribe(agent_input_topic)
            .command(
                RagResponseCommand.Builder()
                .rag_tool(RagTool.Builder().name("UserRag").index(self.index).build())
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the LLM node
        self.workflow = (
            EventDrivenWorkflow.Builder()
            .name("simple_rag_workflow")
            .node(rag_node)
            .build()
        )

        return self
