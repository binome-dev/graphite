import os

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.stream_assistant import StreamAssistant
from grafi.common.topics.output_topic import agent_stream_output_topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm_stream_response_command import LLMStreamResponseCommand
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class SimpleStreamAssistant(StreamAssistant):
    """
    A simple assistant class that uses OpenAI's language model to process input and generate responses.

    This class sets up a workflow with a single LLM node using OpenAI's API, and provides a method
    to run input through this workflow with token-by-token streaming.
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="SimpleStreamAssistant")
    type: str = Field(default="SimpleStreamAssistant")
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    system_message: str = Field(default=None)
    model: str = Field(default="gpt-4o-mini")

    workflow: EventDrivenWorkflow = None

    class Builder(Assistant.Builder):
        """Concrete builder for SimpleStreamAssistant."""

        def __init__(self):
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "SimpleStreamAssistant":
            return SimpleStreamAssistant()

        def api_key(self, api_key: str) -> "SimpleStreamAssistant.Builder":
            self._assistant.api_key = api_key
            return self

        def system_message(
            self, system_message: str
        ) -> "SimpleStreamAssistant.Builder":
            self._assistant.system_message = system_message
            return self

        def model(self, model: str) -> "SimpleStreamAssistant.Builder":
            self._assistant.model = model
            return self

        def build(self) -> "SimpleStreamAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "SimpleStreamAssistant":
        """
        Build the underlying EventDrivenWorkflow with a single LLMStreamNode.
        """
        # Create an LLM node
        llm_node = (
            LLMNode.Builder()
            .name("LLMStreamNode")
            .subscribe(agent_input_topic)
            .command(
                LLMStreamResponseCommand.Builder()
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
            .publish_to(agent_stream_output_topic)
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
