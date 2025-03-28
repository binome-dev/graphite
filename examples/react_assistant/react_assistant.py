# the react assistant applied the ReAct agent design patter
# Question -> thought ----------> action -> output
#                ^                  |
#                |               search tool
#                |--- observation <-|

import os

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


class ReActAssistant(Assistant):
    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="ReActAssistant")
    type: str = Field(default="ReActAssistant")
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    thought_llm_system_message: str = Field(default=None)
    action_llm_system_message: str = Field(default=None)
    observation_llm_system_message: str = Field(default=None)
    summary_llm_system_message: str = Field(default=None)
    search_tool: FunctionTool = Field(default=None)
    model: str = Field(default="gpt-4o-mini")

    class Builder(Assistant.Builder):
        """Concrete builder for ReActAssistant."""

        def __init__(self):
            self._assistant = self._init_assistant()

        def _init_assistant(self) -> "ReActAssistant":
            return ReActAssistant()

        def api_key(self, api_key: str) -> "ReActAssistant.Builder":
            self._assistant.api_key = api_key
            return self

        def thought_llm_system_message(
            self, thought_llm_system_message: str
        ) -> "ReActAssistant.Builder":
            self._assistant.thought_llm_system_message = thought_llm_system_message
            return self

        def action_llm_system_message(
            self, action_llm_system_message: str
        ) -> "ReActAssistant.Builder":
            self._assistant.action_llm_system_message = action_llm_system_message
            return self

        def observation_llm_system_message(
            self, observation_llm_system_message: str
        ) -> "ReActAssistant.Builder":
            self._assistant.observation_llm_system_message = (
                observation_llm_system_message
            )
            return self

        def summary_llm_system_message(
            self, summary_llm_system_message: str
        ) -> "ReActAssistant.Builder":
            self._assistant.summary_llm_system_message = summary_llm_system_message
            return self

        def search_tool(self, search_tool: FunctionTool) -> "ReActAssistant.Builder":
            self._assistant.search_tool = search_tool
            return self

        def model(self, model: str) -> "ReActAssistant.Builder":
            self._assistant.model = model
            return self

        def build(self) -> "ReActAssistant":
            self._assistant._construct_workflow()
            return self._assistant

    def _construct_workflow(self) -> "ReActAssistant":
        workflow_dag_builder = EventDrivenWorkflow.Builder().name(
            "ReActAssistantWorkflow"
        )

        thought_result_topic = Topic(name="thought_result")

        observation_result_topic = Topic(name="observation_result")

        thought_node = (
            LLMNode.Builder()
            .name("ThoughtNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(observation_result_topic)
                .build()
            )
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
                    .name("ThoughtLLMTool")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.thought_llm_system_message)
                    .build()
                )
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
            and msgs[-1].content.strip() != "",
        )

        action_node = (
            LLMNode.Builder()
            .name("ActionNode")
            .subscribe(thought_result_topic)
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
                    .name("ActionLLMTool")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.action_llm_system_message)
                    .build()
                )
                .build()
            )
            .publish_to(action_result_search_topic)
            .publish_to(action_result_finish_topic)
            .build()
        )

        workflow_dag_builder.node(action_node)

        search_function_result_topic = Topic(name="search_function_result")

        search_function_node = (
            LLMFunctionCallNode.Builder()
            .name("SearchFunctionNode")
            .subscribe(action_result_search_topic)
            .command(
                FunctionCallingCommand.Builder().function_tool(self.search_tool).build()
            )
            .publish_to(search_function_result_topic)
            .build()
        )

        workflow_dag_builder.node(search_function_node)

        observation_node = (
            LLMNode.Builder()
            .name("ObservationNode")
            .subscribe(search_function_result_topic)
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
                    .name("ObservationLLMTool")
                    .api_key(self.api_key)
                    .model(self.model)
                    .system_message(self.observation_llm_system_message)
                    .build()
                )
                .build()
            )
            .publish_to(observation_result_topic)
            .build()
        )

        workflow_dag_builder.node(observation_node)

        summaries_node = (
            LLMNode.Builder()
            .name("SummariesNode")
            .subscribe(action_result_finish_topic)
            .command(
                LLMResponseCommand.Builder()
                .llm(
                    OpenAITool.Builder()
                    .name("SummariesLLMTool")
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

        workflow_dag_builder.node(summaries_node)

        self.workflow = workflow_dag_builder.build()

        return self
