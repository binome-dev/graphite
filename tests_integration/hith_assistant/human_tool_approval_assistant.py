import os
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.nodes.conditions import has_no_tool_call
from grafi.nodes.conditions import has_tool_call
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
    """A human-in-the-loop assistant that surfaces a tool call for review.

    This is the plain pause/resume form: the LLM proposes a tool call, the
    function node runs it and publishes the result to a paired
    ``InWorkflowOutputTopic`` (surfacing it to a human), and the human's reply
    resumes the workflow through the LLM, which produces the final answer.
    Routing is content-based on the LLM node's publisher routes
    (``publish_to(..., when=has_tool_call)``); there is a single human-response
    channel and no approve/deny verdict branching.

    Verdict-gated approval (run the tool only if the human approves, deny to
    forward a rejection) is a consumer-router capability introduced with the
    tool-hooks change; this example is intentionally limited to the pause/resume
    mechanics that the pure publisher-route routing supports.

    Attributes:
        name (str): The name of the assistant.
        api_key (str): The API key for OpenAI. If not provided, it tries to use
            the OPENAI_API_KEY environment variable.
        model (str): The name of the OpenAI model to use.
        function_tool (FunctionCallTool): The tool whose call is surfaced for
            human review.
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
    summary_llm_system_message: Optional[str] = Field(default=None)

    @classmethod
    def builder(cls) -> "HumanApprovalAssistantBuilder":
        """Return a builder for HumanApprovalAssistant."""
        return HumanApprovalAssistantBuilder(cls)

    def _construct_workflow(self) -> "HumanApprovalAssistant":
        agent_input_topic = InputTopic(name="agent_input_topic")
        agent_output_topic = OutputTopic(name="agent_output_topic")
        tool_call_topic = Topic(name="human_tool_call_topic")
        register_topic = Topic(name="human_tool_call_response_topic")
        human_response_topic = InWorkflowInputTopic(name="human_response_topic")
        human_request_topic = InWorkflowOutputTopic(
            name="human_tool_call_request_topic",
            paired_in_workflow_input_topic_names=[human_response_topic.name],
        )

        # The human's reply re-enters this node; a tool-call proposal is routed
        # to the function node, a plain answer to the summary node.
        llm_input_node = (
            Node.builder()
            .name("OpenAIInputNode")
            .type("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(human_response_topic)
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
            .publish_to(tool_call_topic, when=has_tool_call)
            .publish_to(register_topic, when=has_no_tool_call)
            .build()
        )

        # The function node runs the proposed tool call and surfaces the result
        # to a human for review via the paired in-workflow output topic.
        function_call_node = (
            Node.builder()
            .name("FunctionCallNode")
            .type("FunctionCallNode")
            .subscribe(SubscriptionBuilder().subscribed_to(tool_call_topic).build())
            .tool(self.function_tool)
            .publish_to(human_request_topic)
            .build()
        )

        # Once the input LLM produces a plain answer (no tool call), summarize it
        # for the user.
        llm_output_node = (
            Node.builder()
            .name("OpenAIOutputNode")
            .type("LLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(register_topic).build())
            .tool(
                OpenAITool.builder()
                .name("UserOutputLLM")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.summary_llm_system_message)
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the nodes
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("HumanApprovalWorkflow")
            .node(llm_input_node)
            .node(function_call_node)
            .node(llm_output_node)
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

    def summary_llm_system_message(self, summary_llm_system_message: str) -> Self:
        self.kwargs["summary_llm_system_message"] = summary_llm_system_message
        return self

    def function_tool(self, function_tool: FunctionCallTool) -> Self:
        self.kwargs["function_tool"] = function_tool
        return self
