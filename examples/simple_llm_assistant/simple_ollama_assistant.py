from typing import Optional, Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.llms.impl.ollama_tool import OllamaTool
from grafi.tools.llms.llm_response_command import LLMResponseCommand
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
    model: str = Field(default="qwen2.5")

    class Builder(Assistant.Builder):
        """Concrete builder for WorkflowDag."""

        _assistant: "SimpleOllamaAssistant"

        def __init__(self) -> None:
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "SimpleOllamaAssistant":
            return SimpleOllamaAssistant.model_construct()

        def api_url(self, api_url: str) -> Self:
            self._assistant.api_url = api_url
            return self

        def system_message(
            self, system_message: str
        ) -> Self:
            self._assistant.system_message = system_message
            return self

        def model(self, model: str) -> Self:
            self._assistant.model = model
            return self

        def build(self) -> "SimpleOllamaAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "SimpleOllamaAssistant":
        # Create an LLM node
        llm_node = (
            LLMNode.Builder()
            .name("OllamaInputNode")
            .subscribe(agent_input_topic)
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OllamaTool.Builder()
                    .name("UserInputLLM")
                    .api_url(self.api_url)
                    .model(self.model)
                    .system_message(self.system_message)
                    .build()
                )
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow with the input node and the LLM node
        self.workflow = (
            EventDrivenWorkflow.Builder()
            .name("simple_function_call_workflow")
            .node(llm_node)
            .build()
        )

        return self
