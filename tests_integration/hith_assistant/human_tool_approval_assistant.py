import os
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.nodes.conditions import has_no_tool_call
from grafi.nodes.conditions import has_tool_call
from grafi.nodes.hooks.hitl_approval_hook import ToolCallReasonHook
from grafi.nodes.impl.hooked_node import HookedNode
from grafi.nodes.routing import ConsumerRouter
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
        # HITL via a consumer-verdict gate on the function node:
        #   * the LLM proposes a tool call and (via ToolCallReasonHook) justifies
        #     it; the call is content-routed to an InWorkflowOutputTopic, which
        #     surfaces for human review and pairs to the resume input.
        #   * the human echoes the call back with a verdict; the function node's
        #     consumer router approves (runs the tool) or denies (forwards the
        #     reply, which the LLM then answers).
        agent_input_topic = InputTopic(name="agent_input_topic")
        agent_output_topic = OutputTopic(name="agent_output_topic")
        function_output_topic = Topic(name="human_tool_call_response_topic")

        human_response_topic = InWorkflowInputTopic(name="human_response_topic")
        in_workflow_output_topic = InWorkflowOutputTopic(
            name="human_tool_call_request_topic",
            paired_in_workflow_input_topic_names=[human_response_topic.name],
        )

        llm_input_node = (
            HookedNode.builder()
            .name("OpenAIInputNode")
            .type("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(function_output_topic)
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
            # Make the model justify each tool call (surfaced to the reviewer).
            .pre_tool_hook(ToolCallReasonHook())
            .publish_to(in_workflow_output_topic, when=has_tool_call)
            .publish_to(agent_output_topic, when=has_no_tool_call)
            .build()
        )

        # The function node gates on the human verdict: approve -> run the
        # (echoed) tool call; deny -> forward the reply back to the LLM.
        function_call_node = (
            HookedNode.builder()
            .name("FunctionCallNode")
            .type("FunctionCallNode")
            .subscribe(
                SubscriptionBuilder().subscribed_to(human_response_topic).build()
            )
            .tool(self.function_tool)
            .consumer_router(ConsumerRouter(pre_hitl_input=human_response_topic.name))
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
