import os
import uuid
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.impl.llm_function_call_node import LLMFunctionCallNode
from grafi.nodes.impl.llm_node import LLMNode
from grafi.tools.function_calls.function_call_command import FunctionCallCommand
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.impl.google_search_tool import GoogleSearchTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.tools.llms.llm_response_command import LLMResponseCommand
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


AGENT_SYSTEM_MESSAGE = """
You are a helpful and knowledgeable agent. To achieve your goal of answering complex questions
correctly, you have access to the search tool.

To answer questions, you'll need to go through multiple steps involving step-by-step thinking and
selecting search tool if necessary.

Response in a concise and clear manner, ensuring that your answers are accurate and relevant to the user's query.
"""


class SimpleAgent(Assistant):
    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="SimpleAgent")
    type: str = Field(default="SimpleAgent")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    system_prompt: Optional[str] = Field(default=AGENT_SYSTEM_MESSAGE)
    function_call_tool: FunctionCallTool = Field(
        default=GoogleSearchTool.builder()
        .name("GoogleSearchTool")
        .fixed_max_results(3)
        .build()
    )
    model: str = Field(default="gpt-4o-mini")

    @classmethod
    def builder(cls) -> "SimpleAgentBuilder":
        """Return a builder for SimpleAgent."""
        return SimpleAgentBuilder(cls)

    def _construct_workflow(self) -> "SimpleAgent":
        function_call_topic = Topic(
            name="function_call_topic",
            condition=lambda msgs: msgs[-1].tool_calls
            is not None,  # only when the last message is a function call
        )
        function_result_topic = Topic(name="function_result_topic")

        agent_output_topic.condition = (
            lambda msgs: msgs[-1].content is not None
            and isinstance(msgs[-1].content, str)
            and msgs[-1].content.strip() != ""
        )

        llm_node = (
            LLMNode.builder()
            .name("OpenAIInputNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .command(
                LLMResponseCommand.builder()
                .llm(
                    OpenAITool.builder()
                    .name("UserInputLLM")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.system_prompt)
                    .build()
                )
                .build()
            )
            .publish_to(function_call_topic)
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a function call node
        function_call_node = (
            LLMFunctionCallNode.builder()
            .name("FunctionCallNode")
            .subscribe(SubscriptionBuilder().subscribed_to(function_call_topic).build())
            .command(
                FunctionCallCommand.builder()
                .function_call_tool(self.function_call_tool)
                .build()
            )
            .publish_to(function_result_topic)
            .build()
        )

        # Create a workflow and add the nodes
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("simple_agent_workflow")
            .node(llm_node)
            .node(function_call_node)
            .build()
        )

        return self

    def run(self, qestion: str):
        execution_context = ExecutionContext(
            conversation_id=uuid.uuid4().hex,
            execution_id=uuid.uuid4().hex,
            assistant_request_id=uuid.uuid4().hex,
        )

        # Test the run method
        input_data = [
            Message(
                role="user",
                content=qestion,
            )
        ]

        output = super().execute(execution_context, input_data)

        return output[0].content


class SimpleAgentBuilder(AssistantBaseBuilder[SimpleAgent]):
    """Concrete builder for SimpleAgent."""

    def api_key(self, api_key: str) -> Self:
        self._obj.api_key = api_key
        return self

    def system_prompt(self, system_prompt: str) -> Self:
        self._obj.system_prompt = system_prompt
        return self

    def model(self, model: str) -> Self:
        self._obj.model = model
        return self

    def function_call_tool(self, function_call_tool: FunctionCallTool) -> Self:
        self._obj.function_call_tool = function_call_tool
        return self


def create_agent(
    system_prompt: Optional[str] = None,
    function_call_tool: Optional[FunctionCallTool] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> SimpleAgent:
    builder = SimpleAgent.builder()

    if system_prompt:
        builder.system_prompt(system_prompt)
    if function_call_tool:
        builder.function_call_tool(function_call_tool)
    if model:
        builder.model(model)
    if api_key:
        builder.api_key(api_key)
    return builder.build()
