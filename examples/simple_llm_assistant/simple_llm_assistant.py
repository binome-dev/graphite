import os

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm_response_command import LLMResponseCommand
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
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    system_message: str = Field(default=None)
    model: str = Field(default="gpt-4o-mini")

    workflow: EventDrivenWorkflow = None

    class Builder(Assistant.Builder):
        """Concrete builder for WorkflowDag."""

        def __init__(self):
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "SimpleLLMAssistant":
            return SimpleLLMAssistant()

        def api_key(self, api_key: str) -> "SimpleLLMAssistant.Builder":
            self._assistant.api_key = api_key
            return self

        def system_message(self, system_message: str) -> "SimpleLLMAssistant.Builder":
            self._assistant.system_message = system_message
            return self

        def model(self, model: str) -> "SimpleLLMAssistant.Builder":
            self._assistant.model = model
            return self

        def build(self) -> "SimpleLLMAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "SimpleLLMAssistant":
        # Create an LLM node
        llm_node = (
            LLMNode.Builder()
            .name("OpenAINode")
            .subscribe(agent_input_topic)
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
                    .name("OpenAITool")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.system_message)
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
            .name("SimpleLLMWorkflow")
            .node(llm_node)
            .build()
        )

        return self
