# the react assistant applied the ReAct agent design patter
# Question -> thought ----------> action -> output
#                ^                  |
#                |               search tool
#                |--- observation <-|

import os
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.common.topics.output_topic import agent_output_topic
from grafi.common.topics.subscription_builder import SubscriptionBuilder
from grafi.common.topics.topic import Topic
from grafi.common.topics.topic import agent_input_topic
from grafi.nodes.node import Node
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class ReActAssistant(Assistant):
    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="ReActAssistant")
    type: str = Field(default="ReActAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    thought_llm_system_message: Optional[str] = Field(default=None)
    action_llm_system_message: Optional[str] = Field(default=None)
    observation_llm_system_message: Optional[str] = Field(default=None)
    summary_llm_system_message: Optional[str] = Field(default=None)
    search_tool: FunctionCallTool
    model: str = Field(default="gpt-4o-mini")

    @classmethod
    def builder(cls) -> "ReActAssistantBuilder":
        """Return a builder for ReActAssistant."""
        return ReActAssistantBuilder(cls)

    def _construct_workflow(self) -> "ReActAssistant":
        workflow_dag_builder = EventDrivenWorkflow.builder().name(
            "ReActAssistantWorkflow"
        )

        thought_result_topic = Topic(name="thought_result")

        observation_result_topic = Topic(name="observation_result")

        thought_node = (
            Node.builder()
            .name("ThoughtNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(observation_result_topic)
                .build()
            )
            .tool(
                OpenAITool.builder()
                .name("ThoughtLLMTool")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.thought_llm_system_message)
                .build()
            )
            .publish_to(thought_result_topic)
            .build()
        )

        workflow_dag_builder.node(thought_node)

        action_result_search_topic = Topic(
            name="action_search_result",
            condition=lambda msgs: msgs[-1].tool_calls is not None,
        )
        action_result_finish_topic = Topic(
            name="action_finish_result",
            condition=lambda msgs: msgs[-1].content is not None
            and isinstance(msgs[-1].content, str)
            and msgs[-1].content.strip() != "",
        )

        action_node = (
            Node.builder()
            .name("ActionNode")
            .subscribe(thought_result_topic)
            .tool(
                OpenAITool.builder()
                .name("ActionLLMTool")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.action_llm_system_message)
                .build()
            )
            .publish_to(action_result_search_topic)
            .publish_to(action_result_finish_topic)
            .build()
        )

        workflow_dag_builder.node(action_node)

        search_function_result_topic = Topic(name="search_function_result")

        search_function_node = (
            Node.builder()
            .name("SearchNode")
            .subscribe(action_result_search_topic)
            .tool(self.search_tool)
            .publish_to(search_function_result_topic)
            .build()
        )

        workflow_dag_builder.node(search_function_node)

        observation_node = (
            Node.builder()
            .name("ObservationNode")
            .subscribe(search_function_result_topic)
            .tool(
                OpenAITool.builder()
                .name("ObservationLLMTool")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.observation_llm_system_message)
                .build()
            )
            .publish_to(observation_result_topic)
            .build()
        )

        workflow_dag_builder.node(observation_node)

        summaries_node = (
            Node.builder()
            .name("SummariesNode")
            .subscribe(action_result_finish_topic)
            .tool(
                OpenAITool.builder()
                .name("SummariesLLMTool")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.summary_llm_system_message)
                .build()
            )
            .publish_to(agent_output_topic)
            .build()
        )

        workflow_dag_builder.node(summaries_node)

        self.workflow = workflow_dag_builder.build()

        return self


class ReActAssistantBuilder(AssistantBaseBuilder[ReActAssistant]):
    """Concrete builder for ReActAssistant."""

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def thought_llm_system_message(self, thought_llm_system_message: str) -> Self:
        self.kwargs["thought_llm_system_message"] = thought_llm_system_message
        return self

    def action_llm_system_message(self, action_llm_system_message: str) -> Self:
        self.kwargs["action_llm_system_message"] = action_llm_system_message
        return self

    def observation_llm_system_message(
        self, observation_llm_system_message: str
    ) -> Self:
        self.kwargs["observation_llm_system_message"] = observation_llm_system_message
        return self

    def summary_llm_system_message(self, summary_llm_system_message: str) -> Self:
        self.kwargs["summary_llm_system_message"] = summary_llm_system_message
        return self

    def search_tool(self, search_tool: FunctionCallTool) -> Self:
        self.kwargs["search_tool"] = search_tool
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self
