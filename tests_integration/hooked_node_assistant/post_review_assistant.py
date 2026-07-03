import os
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.nodes.hooks import HITLApprovalHook
from grafi.nodes.impl.hooked_node import HookedNode
from grafi.nodes.routing import ConsumerRouter
from grafi.nodes.routing import Stage
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow


class AnnouncementReviewAssistant(Assistant):
    """
    An assistant that drafts a company announcement and pauses it for
    editorial review BEFORE release -- a post-generation review gate on a
    single HookedNode.

    Every draft the LLM produces is paused (post-tool HITLApprovalHook) on an
    in-workflow output topic for a human editor. On approval the EXACT
    reviewed draft is recovered from the event store and released without
    re-invoking the LLM: the release is deterministic (what was reviewed is
    what ships) and the approval costs no second LLM call. On denial the
    reviewer's feedback is forwarded to the output route instead.

    Attributes:
        name (str): The name of the assistant.
        api_key (str): The API key for OpenAI. If not provided, it tries to
            use the OPENAI_API_KEY environment variable.
        model (str): The name of the OpenAI model to use.
        drafting_system_message (str): The system message for the drafting LLM.
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="AnnouncementReviewAssistant")
    type: str = Field(default="AnnouncementReviewAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default="gpt-4o-mini")
    drafting_system_message: str = Field(
        default=(
            "You draft short, factual company announcements from the user's "
            "notes. Keep the announcement to a few sentences, professional in "
            "tone, and stick strictly to the facts in the notes."
        )
    )

    @classmethod
    def builder(cls) -> "AnnouncementReviewAssistantBuilder":
        """Return a builder for AnnouncementReviewAssistant."""
        return AnnouncementReviewAssistantBuilder(cls)

    def _construct_workflow(self) -> "AnnouncementReviewAssistant":
        # Post-generation review gate on a single node:
        #   * the LLM drafts the announcement; the post-tool HITLApprovalHook
        #     pauses the draft to review_request_topic for the editor.
        #   * the editor's reply arrives on review_response_topic; the
        #     consumer router classifies its verdict: approve -> the reviewed
        #     draft is recovered from the event store and released (the LLM is
        #     NOT re-run); deny -> the reply is forwarded instead.
        agent_input_topic = InputTopic(name="agent_input_topic")
        agent_output_topic = OutputTopic(name="agent_output_topic")

        review_response_topic = InWorkflowInputTopic(name="review_response_topic")
        review_request_topic = InWorkflowOutputTopic(
            name="review_request_topic",
            paired_in_workflow_input_topic_names=[review_response_topic.name],
        )

        drafting_node = (
            HookedNode.builder()
            .name("AnnouncementDraftNode")
            .type("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(review_response_topic)
                .build()
            )
            .tool(
                OpenAITool.builder()
                .name("AnnouncementDraftLLM")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.drafting_system_message)
                .build()
            )
            # Every draft pauses for editorial review after the LLM runs.
            .post_tool_hook(HITLApprovalHook())
            .consumer_router(ConsumerRouter(post_hitl_input=review_response_topic.name))
            .publish_to(agent_output_topic)
            .publish_to(review_request_topic, from_stage=Stage.POST_HOOK)
            .build()
        )

        # Create a workflow and add the node
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("AnnouncementReviewWorkflow")
            .node(drafting_node)
            .build()
        )

        return self


class AnnouncementReviewAssistantBuilder(
    AssistantBaseBuilder[AnnouncementReviewAssistant]
):
    """Concrete builder for AnnouncementReviewAssistant."""

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self

    def drafting_system_message(self, drafting_system_message: str) -> Self:
        self.kwargs["drafting_system_message"] = drafting_system_message
        return self
