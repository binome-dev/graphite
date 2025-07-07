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
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class SimpleStreamFunctionCallAssistant(Assistant):
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
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    system_message: Optional[str] = Field(default=None)
    model: str = Field(default="gpt-4o-mini")
    function_call_llm_system_message: Optional[str] = Field(default=None)
    summary_llm_system_message: Optional[str] = Field(default=None)
    function_tool: FunctionCallTool

    @classmethod
    def builder(cls) -> "SimpleStreamFunctionCallAssistantBuilder":
        """Return a builder for SimpleStreamFunctionCallAssistant."""
        return SimpleStreamFunctionCallAssistantBuilder(cls)

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
            Node.builder()
            .name("OpenAIInputNode")
            .type("OpenAIInputNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input_topic).build())
            .tool(
                OpenAITool.builder()
                .name("UserInputLLM")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.function_call_llm_system_message)
                .build()
            )
            .publish_to(function_call_topic)
            .publish_to(summary_topic)
            .build()
        )

        # Create a function call node

        function_result_topic = Topic(name="function_result_topic")

        function_call_node = (
            Node.builder()
            .name("FunctionCallNode")
            .type("FunctionCallNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .tool(self.function_tool)
            .publish_to(function_result_topic)
            .build()
        )

        # Create an LLM node
        llm_node = (
            Node.builder()
            .name("LLMStreamNode")
            .type("LLMStreamNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(function_result_topic)
                .or_()
                .subscribed_to(summary_topic)
                .build()
            )
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
            .name("simple_stream_function_call_workflow")
            .node(llm_input_node)
            .node(function_call_node)
            .node(llm_node)
            .build()
        )
        return self


class SimpleStreamFunctionCallAssistantBuilder(
    AssistantBaseBuilder[SimpleStreamFunctionCallAssistant]
):
    """Concrete builder for SimpleStreamFunctionCallAssistant."""

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def system_message(self, system_message: str) -> Self:
        self.kwargs["system_message"] = system_message
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self

    def function_call_llm_system_message(
        self, function_call_llm_system_message: str
    ) -> Self:
        self.kwargs[
            "function_call_llm_system_message"
        ] = function_call_llm_system_message
        return self

    def summary_llm_system_message(self, summary_llm_system_message: str) -> Self:
        self.kwargs["summary_llm_system_message"] = summary_llm_system_message
        return self

    def function_tool(self, function_tool: FunctionCallTool) -> Self:
        self.kwargs["function_tool"] = function_tool
        return self
