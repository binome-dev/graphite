from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.node import Node
from grafi.tools.llms.impl.ollama_tool import OllamaTool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class SimpleOllamaAssistant(Assistant):
    """
    A simple assistant class that uses OpenAI's language model to process input and generate responses.

    This class sets up a workflow with a single LLM node using OpenAI's API, and provides a method
    to run input through this workflow.

    Attributes:
        api_url (str): The API url for Ollama.
        model (str): The name of the OpenAI model to use.
        event_store (EventStore): An instance of EventStore to record events during the assistant's operation.
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="SimpleOllamaAssistant")
    type: str = Field(default="SimpleOllamaAssistant")
    api_url: str = Field(default="http://localhost:11434")
    system_message: Optional[str] = Field(default=None)
    model: str = Field(default="qwen3")

    @classmethod
    def builder(cls) -> "SimpleOllamaAssistantBuilder":
        """Return a builder for Node."""
        return SimpleOllamaAssistantBuilder(cls)

    def _construct_workflow(self) -> "SimpleOllamaAssistant":
        # Create an LLM node
        llm_node = (
            Node.builder()
            .name("OllamaInputNode")
            .type("LLMNode")
            .subscribe(agent_input_topic)
            .tool(
                OllamaTool.builder()
                .name("UserInputLLM")
                .api_url(self.api_url)
                .model(self.model)
                .system_message(self.system_message)
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow with the input node and the LLM node
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("simple_function_call_workflow")
            .node(llm_node)
            .build()
        )

        return self


class SimpleOllamaAssistantBuilder(AssistantBaseBuilder[SimpleOllamaAssistant]):
    """Concrete builder for SimpleLLMAssistant."""

    def api_url(self, api_url: str) -> Self:
        self.kwargs["api_url"] = api_url
        return self

    def system_message(self, system_message: str) -> Self:
        self.kwargs["system_message"] = system_message
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self
