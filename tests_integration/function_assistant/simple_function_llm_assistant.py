import os
from typing import Callable
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
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


OutputType = type


class SimpleFunctionLLMAssistant(Assistant):
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
    name: str = Field(default="SimpleFunctionLLMAssistant")
    type: str = Field(default="SimpleFunctionLLMAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default="gpt-4o-mini")
    output_format: OutputType
    function: Callable

    @classmethod
    def builder(cls) -> "SimpleFunctionLLMAssistantBuilder":
        """Return a builder for SimpleFunctionLLMAssistant."""
        return SimpleFunctionLLMAssistantBuilder(cls)

    def _construct_workflow(self) -> "SimpleFunctionLLMAssistant":
        function_topic = Topic(name="function_call_topic")

        llm_input_node = (
            Node.builder()
            .name("OpenAIInputNode")
            .type("LLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input_topic).build())
            .tool(
                OpenAITool.builder()
                .name("UserInputLLM")
                .api_key(self.api_key)
                .model(self.model)
                .chat_params({"response_format": self.output_format})
                .build()
            )
            .publish_to(function_topic)
            .build()
        )

        # Create a function node

        function_call_node = (
            Node.builder()
            .name("FunctionCallNode")
            .type("FunctionCallNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_topic).build())
            .tool(FunctionTool.builder().function(self.function).build())
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the nodes
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("simple_function_call_workflow")
            .node(llm_input_node)
            .node(function_call_node)
            .build()
        )

        return self


class SimpleFunctionLLMAssistantBuilder(
    AssistantBaseBuilder[SimpleFunctionLLMAssistant]
):
    """
    Builder for SimpleFunctionLLMAssistant.

    This class provides methods to set the API key, model, output format, and function for the assistant.
    """

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self

    def output_format(self, output_format: OutputType) -> Self:
        self.kwargs["output_format"] = output_format
        return self

    def function(self, function: Callable) -> Self:
        self.kwargs["function"] = function
        return self
