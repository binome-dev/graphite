import os
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class HumanApprovalAssistant(Assistant):
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
    name: str = Field(default="HumanApprovalAssistant")
    type: str = Field(default="HumanApprovalAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default="gpt-4o")
    function_tool: FunctionCallTool
    function_call_llm_system_message: Optional[str] = Field(default=None)

    @classmethod
    def builder(cls) -> "HumanApprovalAssistantBuilder":
        """Return a builder for HumanApprovalAssistant."""
        return HumanApprovalAssistantBuilder(cls)

    def _construct_workflow(self) -> "HumanApprovalAssistant":
        agent_input_topic = InputTopic(name="agent_input_topic")
        agent_output_topic = OutputTopic(
            name="agent_output_topic",
            condition=lambda msgs: msgs[-1].tool_calls is None,
        )
        in_workflow_input_approval_topic = InWorkflowInputTopic(
            name="human_approval_topic",
            condition=lambda msgs: msgs[-1].content == "YES",
        )
        in_workflow_input_disapproval_topic = InWorkflowInputTopic(
            name="human_disapproval_topic",
            condition=lambda msgs: msgs[-1].content.startswith("NO"),  # type: ignore
        )
        in_workflow_output_topic = InWorkflowOutputTopic(
            name="human_tool_call_request_topic",
            paired_in_workflow_input_topic_names=[
                in_workflow_input_approval_topic.name,
                in_workflow_input_disapproval_topic.name,
            ],
            condition=lambda msgs: msgs[-1].tool_calls is not None,
        )

        function_output_topic = Topic(name="human_tool_call_response_topic")

        llm_input_node = (
            Node.builder()
            .name("OpenAIInputNode")
            .type("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(function_output_topic)
                .or_()
                .subscribed_to(in_workflow_input_disapproval_topic)
                .build()
            )
            .tool(
                OpenAITool.builder()
                .name("UserInputLLM")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.function_call_llm_system_message)
                .build()
            )
            .publish_to(in_workflow_output_topic)
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a function call node

        function_call_node = (
            Node.builder()
            .name("FunctionCallNode")
            .type("FunctionCallNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(in_workflow_input_approval_topic)
                .build()
            )
            .tool(self.function_tool)
            .publish_to(function_output_topic)
            .build()
        )

        # Create a workflow and add the nodes
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("HumanApprovalWorkflow")
            .node(llm_input_node)
            .node(function_call_node)
            .build()
        )

        return self


class HumanApprovalAssistantBuilder(AssistantBaseBuilder[HumanApprovalAssistant]):
    """Concrete builder for HumanApprovalAssistant."""

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self

    def function_call_llm_system_message(
        self, function_call_llm_system_message: str
    ) -> Self:
        self.kwargs["function_call_llm_system_message"] = (
            function_call_llm_system_message
        )
        return self

    def function_tool(self, function_tool: FunctionCallTool) -> Self:
        self.kwargs["function_tool"] = function_tool
        return self
