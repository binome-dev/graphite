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
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.async_result import async_func_wrapper
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.function_calls.impl.tavily_tool import TavilyTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
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
        default=TavilyTool.builder()
        .name("TavilyTestTool")
        .api_key(os.getenv("TAVILY_API_KEY"))
        .max_tokens(6000)
        .search_depth("advanced")
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
            condition=lambda event: event.data[-1].tool_calls
            is not None,  # only when the last message is a function call
        )
        function_result_topic = Topic(name="function_result_topic")

        agent_input_topic = InputTopic(name="agent_input_topic")

        agent_output_topic = OutputTopic(
            name="agent_output_topic",
            condition=lambda event: event.data[-1].content is not None
            and isinstance(event.data[-1].content, str)
            and event.data[-1].content.strip() != "",
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
    ) -> PublishToTopicEvent:
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

        return PublishToTopicEvent(
            invoke_context=invoke_context,
            data=input_data,
        )

    async def run(
        self, question: str, invoke_context: Optional[InvokeContext] = None
    ) -> str:
        output = await async_func_wrapper(
            super().invoke(self.get_input(question, invoke_context))
        )

        return output[0].data[0].content

    async def a_run(
        self, question: str, invoke_context: Optional[InvokeContext] = None
    ) -> AsyncGenerator[Message, None]:
        async for output in super().invoke(self.get_input(question, invoke_context)):
            for message in output.data:
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
