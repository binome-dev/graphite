import os
import uuid
from typing import AsyncGenerator
from typing import Optional
from typing import Self

from loguru import logger
from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.impl.google_search_tool import GoogleSearchTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


AGENT_SYSTEM_MESSAGE = """
You are a helpful and knowledgeable agent. To achieve your goal of answering complex questions
correctly, you have access to the search tool.

To answer questions, you'll need to go through multiple steps involving step-by-step thinking and
selecting search tool if necessary.

Response in a concise and clear manner, ensuring that your answers are accurate and relevant to the user's query.
"""

CONVERSATION_ID = uuid.uuid4().hex


class ReActAgent(Assistant):
    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="ReActAgent")
    type: str = Field(default="ReActAgent")
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
    def builder(cls) -> "ReActAgentBuilder":
        """Return a builder for ReActAgent."""
        return ReActAgentBuilder(cls)

    def _construct_workflow(self) -> "ReActAgent":
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
            Node.builder()
            .name("OpenAIInputNode")
            .type("OpenAIInputNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(function_result_topic)
                .build()
            )
            .tool(
                OpenAITool.builder()
                .name("UserInputLLM")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.system_prompt)
                .build()
            )
            .publish_to(function_call_topic)
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a function call node

        function_call_node = Node(
            name="Node",
            type="Node",
            tool=self.function_call_tool,
            subscribed_expressions=[
                SubscriptionBuilder().subscribed_to(function_call_topic).build()
            ],
            publish_to=[function_result_topic],
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

    def get_input(
        self, question: str, invoke_context: Optional[InvokeContext] = None
    ) -> list[Message]:
        if invoke_context is None:
            logger.debug(
                "Creating new InvokeContext with default conversation id for ReActAgent"
            )
            invoke_context = InvokeContext(
                conversation_id=CONVERSATION_ID,
                invoke_id=uuid.uuid4().hex,
                assistant_request_id=uuid.uuid4().hex,
            )

        # Prepare the input data
        input_data = [
            Message(
                role="user",
                content=question,
            )
        ]

        return input_data, invoke_context

    def run(self, question: str, invoke_context: Optional[InvokeContext] = None) -> str:
        input_data, invoke_context = self.get_input(question, invoke_context)

        output = super().invoke(invoke_context, input_data)

        return output[0].content

    async def a_run(
        self, question: str, invoke_context: Optional[InvokeContext] = None
    ) -> AsyncGenerator[Message, None]:
        input_data, invoke_context = self.get_input(question, invoke_context)

        async for output in super().a_invoke(invoke_context, input_data):
            for message in output:
                yield message


class ReActAgentBuilder(AssistantBaseBuilder[ReActAgent]):
    """Concrete builder for ReActAgent."""

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def system_prompt(self, system_prompt: str) -> Self:
        self.kwargs["system_prompt"] = system_prompt
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self

    def function_call_tool(self, function_call_tool: FunctionCallTool) -> Self:
        self.kwargs["function_call_tool"] = function_call_tool
        return self


def create_react_agent(
    system_prompt: Optional[str] = None,
    function_call_tool: Optional[FunctionCallTool] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> ReActAgent:
    builder = ReActAgent.builder()

    if system_prompt:
        builder.system_prompt(system_prompt)
    if function_call_tool:
        builder.function_call_tool(function_call_tool)
    if model:
        builder.model(model)
    if api_key:
        builder.api_key(api_key)
    return builder.build()
