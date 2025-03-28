import os

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.common.topics.human_request_topic import human_request_topic
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic, agent_input_topic
from grafi.nodes.impl.llm_function_call_node import LLMFunctionCallNode
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.functions.function_calling_command import FunctionCallingCommand
from grafi.tools.functions.function_tool import FunctionTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm_response_command import LLMResponseCommand
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class SimpleHITLAssistant(Assistant):
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
    name: str = Field(default="SimpleHITLAssistant")
    type: str = Field(default="SimpleHITLAssistant")
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default="gpt-4o-mini")
    hitl_llm_system_message: str = Field(default=None)
    summary_llm_system_message: str = Field(default=None)
    hitl_request: FunctionTool = Field(default=None)

    class Builder(Assistant.Builder):
        """Concrete builder for SimpleHITLAssistant."""

        def __init__(self):
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "SimpleHITLAssistant":
            return SimpleHITLAssistant()

        def api_key(self, api_key: str) -> "SimpleHITLAssistant.Builder":
            self._assistant.api_key = api_key
            return self

        def model(self, model: str) -> "SimpleHITLAssistant.Builder":
            self._assistant.model = model
            return self

        def hitl_llm_system_message(
            self, hitl_llm_system_message: str
        ) -> "SimpleHITLAssistant.Builder":
            self._assistant.hitl_llm_system_message = hitl_llm_system_message
            return self

        def summary_llm_system_message(
            self, summary_llm_system_message: str
        ) -> "SimpleHITLAssistant.Builder":
            self._assistant.summary_llm_system_message = summary_llm_system_message
            return self

        def hitl_request(
            self, hitl_request: FunctionTool
        ) -> "SimpleHITLAssistant.Builder":
            self._assistant.hitl_request = hitl_request
            return self

        def build(self) -> "SimpleHITLAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "SimpleHITLAssistant":
        hitl_call_topic = Topic(
            name="hitl_call_topic",
            condition=lambda msgs: msgs[-1].tool_calls is not None,
        )

        register_user_topic = Topic(
            name="register_user_topic",
            condition=lambda msgs: msgs[-1].tool_calls is None,
        )

        llm_input_node = (
            LLMNode.Builder()
            .name("OpenAIInputNode")
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
                    .name("UserInputLLM")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.hitl_llm_system_message)
                    .build()
                )
                .build()
            )
            .publish_to(hitl_call_topic)
            .publish_to(register_user_topic)
            .build()
        )

        # Create a function call node

        function_call_node = (
            LLMFunctionCallNode.Builder()
            .name("FunctionCallNode")
            .subscribe(SubscriptionBuilder().subscribed_to(hitl_call_topic).build())
            .command(
                FunctionCallingCommand.Builder()
                .function_tool(self.hitl_request)
                .build()
            )
            .publish_to(human_request_topic)
            .build()
        )

        # Create an output LLM node
        llm_output_node = (
            LLMNode.Builder()
            .name("OpenAIOutputNode")
            .subscribe(SubscriptionBuilder().subscribed_to(register_user_topic).build())
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
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
            EventDrivenWorkflow.Builder()
            .name("simple_function_call_workflow")
            .node(llm_input_node)
            .node(function_call_node)
            .node(llm_output_node)
            .build()
        )

        return self
