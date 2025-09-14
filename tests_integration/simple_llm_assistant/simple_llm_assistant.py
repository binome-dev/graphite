import os
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.nodes.node import Node
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class SimpleLLMAssistant(Assistant):
    """
    A simple assistant class that uses OpenAI's language model to process input and generate responses.

    This class sets up a workflow with a single LLM node using OpenAI's API, and provides a method
    to run input through this workflow.

    Attributes:
        api_key (str): The API key for OpenAI. If not provided, it tries to use the OPENAI_API_KEY environment variable.
        model (str): The name of the OpenAI model to use.
        event_store (EventStore): An instance of EventStore to record events during the assistant's operation.
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="SimpleLLMAssistant")
    type: str = Field(default="SimpleLLMAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    system_message: Optional[str] = Field(default=None)
    model: str = Field(default="gpt-4o-mini")

    @classmethod
    def builder(cls) -> "SimpleLLMAssistantBuilder":
        """Return a builder for SimpleLLMAssistant."""
        return SimpleLLMAssistantBuilder(cls)

    def _construct_workflow(self) -> "SimpleLLMAssistant":
        agent_input_topic = InputTopic(name="agent_input_topic")
        agent_output_topic = OutputTopic(name="agent_output_topic")
        # Create an LLM node
        llm_node = (
            Node.builder()
            .name("OpenAINode")
            .subscribe(agent_input_topic)
            .tool(
                OpenAITool.builder()
                .name("OpenAITool")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.system_message)
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the LLM node
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("SimpleLLMWorkflow")
            .node(llm_node)
            .build()
        )

        return self


class SimpleLLMAssistantBuilder(AssistantBaseBuilder[SimpleLLMAssistant]):
    """Concrete builder for SimpleLLMAssistant."""

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def system_message(self, system_message: str) -> Self:
        self.kwargs["system_message"] = system_message
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self
