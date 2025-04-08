import os

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.topics.human_request_topic import human_request_topic
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.impl.llm_function_call_node import LLMFunctionCallNode
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.functions.function_calling_command import FunctionCallingCommand
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm_response_command import LLMResponseCommand
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class KycAssistant(Assistant):
    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="KycAssistant")
    type: str = Field(default="KycAssistant")
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default="gpt-4o-mini")
    user_info_extract_system_message: str = Field(default=None)
    action_llm_system_message: str = Field(default=None)
    summary_llm_system_message: str = Field(default=None)
    hitl_request: FunctionTool = Field(default=None)
    register_request: FunctionTool = Field(default=None)

    class Builder(Assistant.Builder):
        """Concrete builder for KycAssistant."""

        def __init__(self):
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "KycAssistant":
            return KycAssistant()

        def api_key(self, api_key: str) -> "KycAssistant.Builder":
            self._assistant.api_key = api_key
            return self

        def model(self, model: str) -> "KycAssistant.Builder":
            self._assistant.model = model
            return self

        def user_info_extract_system_message(
            self, user_info_extract_system_message: str
        ) -> "KycAssistant.Builder":
            self._assistant.user_info_extract_system_message = (
                user_info_extract_system_message
            )
            return self

        def action_llm_system_message(
            self, action_llm_system_message: str
        ) -> "KycAssistant.Builder":
            self._assistant.action_llm_system_message = action_llm_system_message
            return self

        def summary_llm_system_message(
            self, summary_llm_system_message: str
        ) -> "KycAssistant.Builder":
            self._assistant.summary_llm_system_message = summary_llm_system_message
            return self

        def hitl_request(self, hitl_request: FunctionTool) -> "KycAssistant.Builder":
            self._assistant.hitl_request = hitl_request
            return self

        def register_request(
            self, register_request: FunctionTool
        ) -> "KycAssistant.Builder":
            self._assistant.register_request = register_request
            return self

        def build(self) -> "KycAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "KycAssistant":
        # Create thought node to process user input

        user_info_extract_topic = Topic(name="user_info_extract_topic")

        user_info_extract_node = (
            LLMNode.Builder()
            .name("ThoughtNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(human_request_topic)
                .build()
            )
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
                    .name("ThoughtLLM")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.user_info_extract_system_message)
                    .build()
                )
                .build()
            )
            .publish_to(user_info_extract_topic)
            .build()
        )

        # Create action node

        hitl_call_topic = Topic(
            name="hitl_call_topic",
            condition=lambda msgs: msgs[-1].tool_calls[0].function.name
            != "register_client",
        )

        register_user_topic = Topic(
            name="register_user_topic",
            condition=lambda msgs: msgs[-1].tool_calls[0].function.name
            == "register_client",
        )

        action_node = (
            LLMNode.Builder()
            .name("ActionNode")
            .subscribe(user_info_extract_topic)
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
                    .name("ActionLLM")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.action_llm_system_message)
                    .build()
                )
                .build()
            )
            .publish_to(hitl_call_topic)
            .publish_to(register_user_topic)
            .build()
        )

        human_request_function_call_node = (
            LLMFunctionCallNode.Builder()
            .name("HumanRequestNode")
            .subscribe(hitl_call_topic)
            .command(
                FunctionCallingCommand.Builder()
                .function_tool(self.hitl_request)
                .build()
            )
            .publish_to(human_request_topic)
            .build()
        )

        register_user_respond_topic = Topic(name="register_user_respond")

        # Create an output LLM node
        register_user_node = (
            LLMFunctionCallNode.Builder()
            .name("FunctionCallRegisterNode")
            .subscribe(register_user_topic)
            .command(
                FunctionCallingCommand.Builder()
                .function_tool(self.register_request)
                .build()
            )
            .publish_to(register_user_respond_topic)
            .build()
        )

        user_reply_node = (
            LLMNode.Builder()
            .name("LLMResponseToUserNode")
            .subscribe(
                SubscriptionBuilder().subscribed_to(register_user_respond_topic).build()
            )
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
                    .name("ResponseToUserLLM")
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
            EventDrivenWorkflow.Builder()
            .name("simple_function_call_workflow")
            .node(user_info_extract_node)
            .node(action_node)
            .node(human_request_function_call_node)
            .node(register_user_node)
            .node(user_reply_node)
            .build()
        )

        return self
