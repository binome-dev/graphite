import os
from typing import Callable
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.impl.function_node import FunctionNode
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.functions.function_command import FunctionCommand
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm_response_command import LLMResponseCommand
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


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
    output_format: BaseModel
    function: Callable

    class Builder(Assistant.Builder):
        """Concrete builder for SimpleFunctionLLMAssistant."""

        _assistant: "SimpleFunctionLLMAssistant"

        def __init__(self) -> None:
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "SimpleFunctionLLMAssistant":
            return SimpleFunctionLLMAssistant.model_construct()

        def api_key(self, api_key: str) -> Self:
            self._assistant.api_key = api_key
            return self

        def model(self, model: str) -> Self:
            self._assistant.model = model
            return self

        def output_format(self, output_format: type) -> Self:
            self._assistant.output_format = output_format
            return self

        def function(self, function: Callable) -> Self:
            self._assistant.function = function
            return self

        def build(self) -> "SimpleFunctionLLMAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "SimpleFunctionLLMAssistant":
        function_topic = Topic(name="function_call_topic")

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
                    .chat_params({"response_format": self.output_format})
                    .build()
                )
                .build()
            )
            .publish_to(function_topic)
            .build()
        )

        # Create a function node

        function_call_node = (
            FunctionNode.Builder()
            .name("FunctionCallNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_topic).build())
            .command(
                FunctionCommand.Builder()
                .function_tool(FunctionTool.Builder().function(self.function).build())
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the nodes
        self.workflow = (
            EventDrivenWorkflow.Builder()
            .name("simple_function_call_workflow")
            .node(llm_input_node)
            .node(function_call_node)
            .build()
        )

        return self
