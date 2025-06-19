import os
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.impl.llm_function_call_node import LLMFunctionCallNode
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.function_calls.function_call_command import FunctionCallCommand
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.impl.gemini_tool import GeminiTool
from grafi.tools.llms.llm_response_command import LLMResponseCommand
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class SimpleGeminiFunctionCallAssistant(Assistant):
    """
    A simple assistant class that uses OpenAI's language model to process input,
    make function calls, and generate responses.

    This class sets up a workflow with three nodes: an input LLM node, a function call node,
    and an output LLM node. It provides a method to run input through this workflow.

    Attributes:
        name (str): The name of the assistant.
        api_key (str): The API key for OpenAI. If not provided, it tries to use the OPENAI_API_KEY environment variable.
        model (str): The name of the OpenAI model to use.
        event_store (EventStore): An instance of EventStore to record events during the assistant's operation.
        function (Callable): The function to be called by the assistant.
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="SimpleGeminiFunctionCallAssistant")
    type: str = Field(default="SimpleGeminiFunctionCallAssistant")
    api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    model: str = Field(default="gemini-2.0-flash-lite")
    function_call_llm_system_message: Optional[str] = Field(default=None)
    summary_llm_system_message: Optional[str] = Field(default=None)
    function_tool: FunctionCallTool

    @classmethod
    def builder(cls) -> "SimpleGeminiFunctionCallAssistantBuilder":
        """Return a builder for SimpleGeminiFunctionCallAssistant."""
        return SimpleGeminiFunctionCallAssistantBuilder(cls)

    def _construct_workflow(self) -> "SimpleGeminiFunctionCallAssistant":
        function_call_topic = Topic(
            name="function_call_topic",
            condition=lambda msgs: msgs[-1].tool_calls
            is not None,  # only when the last message is a function call
        )

        # Create an input LLM node
        llm_input_node = (
            LLMNode.builder()
            .name("GeminiInputNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input_topic).build())
            .command(
                LLMResponseCommand.builder()
                .llm(
                    GeminiTool.builder()
                    .name("UserInputLLM")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.function_call_llm_system_message)
                    .build()
                )
                .build()
            )
            .publish_to(function_call_topic)
            .publish_to(agent_output_topic)
            .build()
        )

        function_result_topic = Topic(name="function_result_topic")

        agent_output_topic.condition = (
            lambda msgs: msgs[-1].content is not None
            and isinstance(msgs[-1].content, str)
            and msgs[-1].content.strip() != ""
        )

        # Create a function call node
        function_call_node = (
            LLMFunctionCallNode.builder()
            .name("FunctionCallNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .command(
                FunctionCallCommand.builder()
                .function_call_tool(self.function_tool)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        # Create an output LLM node
        llm_output_node = (
            LLMNode.builder()
            .name("GeminiOutputNode")
            .subscribe(
                SubscriptionBuilder().subscribed_to(function_result_topic).build()
            )
            .command(
                LLMResponseCommand.builder()
                .llm(
                    GeminiTool.builder()
                    .name("UserOutputLLM")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.summary_llm_system_message)
                    .build()
                )
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the nodes
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("simple_gemini_function_call_workflow")
            .node(llm_input_node)
            .node(function_call_node)
            .node(llm_output_node)
            .build()
        )

        return self


class SimpleGeminiFunctionCallAssistantBuilder(
    AssistantBaseBuilder[SimpleGeminiFunctionCallAssistant]
):
    """
    Builder for SimpleGeminiFunctionCallAssistant.
    """

    def api_key(self, api_key: str) -> Self:
        self._obj.api_key = api_key
        return self

    def model(self, model: str) -> Self:
        self._obj.model = model
        return self

    def function_call_llm_system_message(
        self, function_call_llm_system_message: str
    ) -> Self:
        self._obj.function_call_llm_system_message = function_call_llm_system_message
        return self

    def summary_llm_system_message(self, summary_llm_system_message: str) -> Self:
        self._obj.summary_llm_system_message = summary_llm_system_message
        return self

    def function_tool(self, function_tool: FunctionCallTool) -> Self:
        self._obj.function_tool = function_tool
        return self
