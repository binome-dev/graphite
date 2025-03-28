import os
from typing import List

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
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


class MultiFunctionsCallAssistant(Assistant):
    """
    A simple assistant class that uses OpenAI's language model to process input,
    make multiple function calls, and generate responses.

    This class sets up a workflow with:
    1. An input node for receiving initial input
    2. An input LLM node for processing the input
    3. Multiple function call nodes (one for each provided function tool)
    4. An output LLM node for generating the final response

    Attributes:
        name (str): The name of the assistant, defaults to "MultiFunctionsCallAssistant"
        type (str): The type of assistant, defaults to "MultiFunctionsCallAssistant"
        api_key (str): The API key for OpenAI. If not provided, uses OPENAI_API_KEY environment variable
        function_call_llm_system_message (str): System message for the function call LLM
        summary_llm_system_message (str): System message for the summary LLM
        model (str): The name of the OpenAI model to use, defaults to "gpt-4o-mini"
        function_tools (List[FunctionTool]): List of function tools to be called by the assistant
        workflow (WorkflowDag): The workflow DAG managing the execution flow
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="MultiFunctionsCallAssistant")
    type: str = Field(default="MultiFunctionsCallAssistant")
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    function_call_llm_system_message: str = Field(default=None)
    summary_llm_system_message: str = Field(default=None)
    model: str = Field(default="gpt-4o-mini")
    function_tools: List[FunctionTool] = Field(default=[])

    class Builder(Assistant.Builder):
        """Concrete builder for MultiFunctionsCallAssistant."""

        def __init__(self):
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "MultiFunctionsCallAssistant":
            return MultiFunctionsCallAssistant()

        def api_key(self, api_key: str) -> "MultiFunctionsCallAssistant.Builder":
            self._assistant.api_key = api_key
            return self

        def function_call_llm_system_message(
            self, function_call_llm_system_message: str
        ) -> "MultiFunctionsCallAssistant.Builder":
            self._assistant.function_call_llm_system_message = (
                function_call_llm_system_message
            )
            return self

        def summary_llm_system_message(
            self, summary_llm_system_message: str
        ) -> "MultiFunctionsCallAssistant.Builder":
            self._assistant.summary_llm_system_message = summary_llm_system_message
            return self

        def model(self, model: str) -> "MultiFunctionsCallAssistant.Builder":
            self._assistant.model = model
            return self

        def function_tool(
            self, function_tool: FunctionTool
        ) -> "MultiFunctionsCallAssistant.Builder":
            self._assistant.function_tools.append(function_tool)
            return self

        def build(self) -> "MultiFunctionsCallAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "MultiFunctionsCallAssistant":
        workflow_dag_builder = EventDrivenWorkflow.Builder().name(
            "MultiFunctionsCallWorkflow"
        )

        function_call_topic = Topic(
            name="function_call_topic",
            condition=lambda msgs: msgs[-1].tool_calls
            is not None,  # only when the last message is a function call
        )

        agent_output_topic.condition = (
            lambda msgs: msgs[-1].content is not None and msgs[-1].content.strip() != ""
        )

        # Create an input LLM node
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
                    .system_message(self.function_call_llm_system_message)
                    .build()
                )
                .build()
            )
            .publish_to(function_call_topic)
            .publish_to(agent_output_topic)
            .build()
        )

        workflow_dag_builder.node(llm_input_node)

        function_result_topic = Topic(
            name="function_result_topic",
            condition=lambda msgs: len(msgs) > 0
            and msgs[-1].content is not None
            and msgs[-1].content.strip() != "",
        )

        # Create function call node
        for function_tool in self.function_tools:
            logger.info(f"Function: {function_tool}")
            function_call_node = (
                LLMFunctionCallNode.Builder()
                .name(f"FunctionCallNode_{function_tool.name}")
                .subscribe(
                    SubscriptionBuilder().subscribed_to(function_call_topic).build()
                )
                .command(
                    FunctionCallingCommand.Builder()
                    .function_tool(function_tool)
                    .build()
                )
                .publish_to(function_result_topic)
                .build()
            )
            workflow_dag_builder.node(function_call_node)

        # Create an output LLM node
        llm_output_node = (
            LLMNode.Builder()
            .name("OpenAIOutputNode")
            .subscribe(
                SubscriptionBuilder().subscribed_to(function_result_topic).build()
            )
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

        workflow_dag_builder.node(llm_output_node)

        self.workflow = workflow_dag_builder.build()

        return self
