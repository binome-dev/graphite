import os

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.stream_assistant import StreamAssistant
from grafi.common.topics.output_topic import agent_stream_output_topic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.impl.llm_function_call_node import LLMFunctionCallNode
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.functions.function_calling_command import FunctionCallingCommand
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm_response_command import LLMResponseCommand
from grafi.tools.llms.llm_stream_response_command import LLMStreamResponseCommand
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class SimpleStreamFunctionCallAssistant(StreamAssistant):
    """
    A simple assistant class that uses OpenAI's language model to process input and generate responses.

    This class sets up a workflow with a single LLM node using OpenAI's API, and provides a method
    to run input through this workflow with token-by-token streaming.
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="SimpleStreamFunctionCallAssistant")
    type: str = Field(default="SimpleStreamFunctionCallAssistant")
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    system_message: str = Field(default=None)
    model: str = Field(default="gpt-4o-mini")
    function_call_llm_system_message: str = Field(default=None)
    summary_llm_system_message: str = Field(default=None)
    function_tool: FunctionTool = Field(default=None)

    workflow: EventDrivenWorkflow = None

    class Builder(Assistant.Builder):
        """Concrete builder for SimpleStreamFunctionCallAssistant."""

        def __init__(self):
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "SimpleStreamFunctionCallAssistant":
            return SimpleStreamFunctionCallAssistant()

        def api_key(self, api_key: str) -> "SimpleStreamFunctionCallAssistant.Builder":
            self._assistant.api_key = api_key
            return self

        def system_message(
            self, system_message: str
        ) -> "SimpleStreamFunctionCallAssistant.Builder":
            self._assistant.system_message = system_message
            return self

        def model(self, model: str) -> "SimpleStreamFunctionCallAssistant.Builder":
            self._assistant.model = model
            return self

        def function_call_llm_system_message(
            self, function_call_llm_system_message: str
        ) -> "SimpleStreamFunctionCallAssistant.Builder":
            self._assistant.function_call_llm_system_message = (
                function_call_llm_system_message
            )
            return self

        def summary_llm_system_message(
            self, summary_llm_system_message: str
        ) -> "SimpleStreamFunctionCallAssistant.Builder":
            self._assistant.summary_llm_system_message = summary_llm_system_message
            return self

        def function_tool(
            self, function_tool: FunctionTool
        ) -> "SimpleStreamFunctionCallAssistant.Builder":
            self._assistant.function_tool = function_tool
            return self

        def build(self) -> "SimpleStreamFunctionCallAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "SimpleStreamFunctionCallAssistant":
        """
        Build the underlying EventDrivenStreamWorkflow with a single LLMStreamNode.
        """
        function_call_topic = Topic(
            name="function_call_topic",
            condition=lambda msgs: msgs[-1].tool_calls
            is not None,  # only when the last message is a function call
        )

        summary_topic = Topic(
            name="summary_topic",
            condition=lambda msgs: msgs[-1].tool_calls
            is None,  # only when the last message is a function call
        )

        llm_input_node = (
            LLMNode.Builder()
            .name("OpenAIInputNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input_topic).build())
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
                    .name("UserInputLLM")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.function_call_llm_system_message)
                    .build()
                )
                .build()
            )
            .publish_to(function_call_topic)
            .publish_to(summary_topic)
            .build()
        )

        # Create a function call node

        function_result_topic = Topic(name="function_result_topic")

        function_call_node = (
            LLMFunctionCallNode.Builder()
            .name("FunctionCallNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .command(
                FunctionCallingCommand.Builder()
                .function_tool(self.function_tool)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        # Create an LLM node
        llm_node = (
            LLMNode.Builder()
            .name("LLMStreamNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(function_result_topic)
                .or_()
                .subscribed_to(summary_topic)
                .build()
            )
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
            .name("simple_stream_function_call_workflow")
            .node(llm_input_node)
            .node(function_call_node)
            .node(llm_node)
            .build()
        )
        return self
