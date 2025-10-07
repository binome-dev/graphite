import os
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.nodes.node import Node
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class MIMOLLMAssistant(Assistant):
    """
    A Multiple Input Multiple Output (MIMO) LLM Assistant that processes multiple input topics
    and produces responses on multiple output topics using OpenAI's language models.
    This assistant creates an event-driven workflow with configurable input/output topics,
    allowing for flexible message routing and processing. It uses OpenAI's API to generate
    responses and can be customized with different models and system messages.
    The assistant automatically sets up the necessary workflow infrastructure including:

    - Agent input and output topics for message handling
    - OpenAI tool integration for LLM processing
    - Event-driven workflow orchestration
        model (str): The name of the OpenAI model to use (default: "gpt-4o-mini").
        system_message (Optional[str]): Optional system message to provide context to the LLM.
        oi_span_type (OpenInferenceSpanKindValues): The span type for OpenInference tracing (default: AGENT).
        name (str): The name of the assistant instance (default: "MIMOLLMAssistant").
        type (str): The type identifier for the assistant (default: "MIMOLLMAssistant").



    Attributes:
        api_key (str): The API key for OpenAI. If not provided, it tries to use the OPENAI_API_KEY environment variable.
        model (str): The name of the OpenAI model to use.
        event_store (EventStore): An instance of EventStore to record events during the assistant's operation.
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="MIMOLLMAssistant")
    type: str = Field(default="MIMOLLMAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    system_message_greeting: Optional[str] = Field(default=None)
    system_message_question: Optional[str] = Field(default=None)
    system_message_merge: Optional[str] = Field(default=None)
    model: str = Field(default="gpt-4o-mini")

    @classmethod
    def builder(cls) -> "MIMOLLMAssistantBuilder":
        """Return a builder for MIMOLLMAssistant."""
        return MIMOLLMAssistantBuilder(cls)

    def _construct_workflow(self) -> "MIMOLLMAssistant":
        agent_input_greeting_topic = InputTopic(
            name="agent_input_greeting_topic",
            condition=lambda msgs: "hello" in str(event.data[-1].content).lower(),
        )
        agent_input_question_topic = InputTopic(
            name="agent_input_question_topic",
            condition=lambda msgs: "question" in str(event.data[-1].content).lower(),
        )
        agent_greeting_output_topic = OutputTopic(name="agent_greeting_output_topic")
        agent_greeting_output_topic = OutputTopic(name="agent_greeting_output_topic")
        agent_output_topic = OutputTopic(name="agent_output_topic")

        agent_greeting_merge_topic = Topic(name="agent_greeting_merge_topic")
        agent_question_merge_topic = Topic(name="agent_question_merge_topic")

        llm_greeting_node = (
            Node.builder()
            .name("OpenAIGreetingNode")
            .subscribe(agent_input_greeting_topic)
            .tool(
                OpenAITool.builder()
                .name("OpenAIToolGreeting")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.system_message_greeting)
                .build()
            )
            .publish_to(agent_greeting_output_topic)
            .publish_to(agent_greeting_merge_topic)
            .build()
        )

        llm_question_node = (
            Node.builder()
            .name("OpenAIQuestionNode")
            .subscribe(agent_input_question_topic)
            .tool(
                OpenAITool.builder()
                .name("OpenAIToolQuestion")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.system_message_question)
                .build()
            )
            .publish_to(agent_greeting_output_topic)
            .publish_to(agent_question_merge_topic)
            .build()
        )

        llm_merge_node = (
            Node.builder()
            .name("OpenAIMergeNode")
            .type("LLMMergeNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_greeting_merge_topic)
                .or_()
                .subscribed_to(agent_question_merge_topic)
                .build()
            )
            .tool(
                OpenAITool.builder()
                .name("OpenAIToolMerge")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(
                    self.system_message_merge
                )  # or a different merge message
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the LLM node
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("MIMOLLMAssistantWorkflow")
            .node(llm_greeting_node)
            .node(llm_question_node)
            .node(llm_merge_node)
            .build()
        )

        return self


class MIMOLLMAssistantBuilder(AssistantBaseBuilder[MIMOLLMAssistant]):
    """Concrete builder for MIMOLLMAssistant."""

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def system_message_greeting(self, system_message: str) -> Self:
        self.kwargs["system_message_greeting"] = system_message
        return self

    def system_message_question(self, system_message: str) -> Self:
        self.kwargs["system_message_question"] = system_message
        return self

    def system_message_merge(self, system_message: str) -> Self:
        self.kwargs["system_message_merge"] = system_message
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self
