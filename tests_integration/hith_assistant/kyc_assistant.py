import os
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.common.topics.human_request_topic import human_request_topic
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class KycAssistant(Assistant):
    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="KycAssistant")
    type: str = Field(default="KycAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default="gpt-4o-mini")
    user_info_extract_system_message: Optional[str] = Field(default=None)
    action_llm_system_message: Optional[str] = Field(default=None)
    summary_llm_system_message: Optional[str] = Field(default=None)
    hitl_request: FunctionCallTool
    register_request: FunctionCallTool

    @classmethod
    def builder(cls) -> "KycAssistantBuilder":
        """Return a builder for KycAssistant."""
        return KycAssistantBuilder(cls)

    def _construct_workflow(self) -> "KycAssistant":
        # Create thought node to process user input

        user_info_extract_topic = Topic(name="user_info_extract_topic")

        user_info_extract_node = (
            Node.builder()
            .name("ThoughtNode")
            .type("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(human_request_topic)
                .build()
            )
            .tool(
                OpenAITool.builder()
                .name("ThoughtLLM")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.user_info_extract_system_message)
                .build()
            )
            .publish_to(user_info_extract_topic)
            .build()
        )

        # Create action node

        hitl_call_topic = Topic(
            name="hitl_call_topic",
            condition=lambda msgs: msgs is not None
            and len(msgs) > 0
            and msgs[-1].tool_calls is not None
            and len(msgs[-1].tool_calls) > 0
            and msgs[-1].tool_calls[0].function.name != "register_client",
        )

        register_user_topic = Topic(
            name="register_user_topic",
            condition=lambda msgs: msgs is not None
            and len(msgs) > 0
            and msgs[-1].tool_calls is not None
            and len(msgs[-1].tool_calls) > 0
            and msgs[-1].tool_calls[0].function.name == "register_client",
        )

        action_node = (
            Node.builder()
            .name("ActionNode")
            .type("LLMNode")
            .subscribe(user_info_extract_topic)
            .tool(
                OpenAITool.builder()
                .name("ActionLLM")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.action_llm_system_message)
                .build()
            )
            .publish_to(hitl_call_topic)
            .publish_to(register_user_topic)
            .build()
        )

        human_request_function_call_node = (
            Node.builder()
            .name("HumanRequestNode")
            .type("FunctionCallNode")
            .subscribe(hitl_call_topic)
            .tool(self.hitl_request)
            .publish_to(human_request_topic)
            .build()
        )

        register_user_respond_topic = Topic(name="register_user_respond")

        # Create an output LLM node
        register_user_node = (
            Node.builder()
            .name("FunctionCallRegisterNode")
            .type("FunctionCallNode")
            .subscribe(register_user_topic)
            .tool(self.register_request)
            .publish_to(register_user_respond_topic)
            .build()
        )

        user_reply_node = (
            Node.builder()
            .name("LLMResponseToUserNode")
            .type("LLMNode")
            .subscribe(
                SubscriptionBuilder().subscribed_to(register_user_respond_topic).build()
            )
            .tool(
                OpenAITool.builder()
                .name("ResponseToUserLLM")
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
            .name("simple_function_call_workflow")
            .node(user_info_extract_node)
            .node(action_node)
            .node(human_request_function_call_node)
            .node(register_user_node)
            .node(user_reply_node)
            .build()
        )

        return self


class KycAssistantBuilder(AssistantBaseBuilder[KycAssistant]):
    """Concrete builder for KycAssistant."""

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self

    def user_info_extract_system_message(
        self, user_info_extract_system_message: str
    ) -> Self:
        self.kwargs[
            "user_info_extract_system_message"
        ] = user_info_extract_system_message
        return self

    def action_llm_system_message(self, action_llm_system_message: str) -> Self:
        self.kwargs["action_llm_system_message"] = action_llm_system_message
        return self

    def summary_llm_system_message(self, summary_llm_system_message: str) -> Self:
        self.kwargs["summary_llm_system_message"] = summary_llm_system_message
        return self

    def hitl_request(self, hitl_request: FunctionCallTool) -> Self:
        self.kwargs["hitl_request"] = hitl_request
        return self

    def register_request(self, register_request: FunctionCallTool) -> Self:
        self.kwargs["register_request"] = register_request
        return self
