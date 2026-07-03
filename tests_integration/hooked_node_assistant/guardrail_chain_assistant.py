import os
import re
from typing import Any
from typing import Dict
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.nodes.hooks import ToolHook
from grafi.nodes.hooks import ToolHookFrame
from grafi.nodes.impl.hooked_node import HookedNode
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"\+?\(?\d[\d\s().-]{6,}\d")

DEFAULT_SUPPORT_SYSTEM_MESSAGE = (
    "You are a customer support agent. Answer the user's question, and always "
    "repeat back exactly which contact details you have on file for the user "
    "(quoting them verbatim from the conversation) so they can confirm them."
)


class RedactPIIHook(ToolHook):
    """Pre-tool guardrail: mask email addresses and phone numbers.

    A pure transform over the frame's messages -- it always PROCEEDs, so the
    node never pauses; the LLM simply never sees the raw PII.
    """

    async def invoke(self, frame: ToolHookFrame) -> ToolHookFrame:
        redacted = []
        for message in frame.messages:
            if not isinstance(message.content, str):
                redacted.append(message)
                continue
            content = EMAIL_PATTERN.sub("[email redacted]", message.content)
            content = PHONE_PATTERN.sub("[phone redacted]", content)
            if content == message.content:
                redacted.append(message)
            else:
                redacted.append(message.model_copy(update={"content": content}))
        frame.messages = redacted
        return frame

    def to_dict(self) -> Dict[str, Any]:
        return {"type": type(self).__name__}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RedactPIIHook":
        return cls()


class DisclaimerHook(ToolHook):
    """Post-tool guardrail: append a disclaimer to the final assistant message.

    A pure transform that always PROCEEDs. Being a non-identity post-hook, it
    makes the node aggregate the LLM stream so the whole reply is stamped once.
    """

    disclaimer: str = Field(
        default="\n\n--\nThis reply was generated with AI assistance."
    )

    async def invoke(self, frame: ToolHookFrame) -> ToolHookFrame:
        if not frame.messages:
            return frame
        last = frame.messages[-1]
        if isinstance(last.content, str):
            frame.messages = frame.messages[:-1] + [
                last.model_copy(update={"content": last.content + self.disclaimer})
            ]
        return frame

    def to_dict(self) -> Dict[str, Any]:
        return {"type": type(self).__name__, "disclaimer": self.disclaimer}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DisclaimerHook":
        if "disclaimer" in data:
            return cls(disclaimer=data["disclaimer"])
        return cls()


class GuardrailSupportAssistant(Assistant):
    """
    A support assistant whose single LLM node carries a guardrail hook chain.

    The pre-tool chain redacts PII from the input before the LLM sees it, and
    the post-tool chain appends a disclaimer to the reply. There is no human in
    the loop: both hooks are pure transforms that always PROCEED, so the
    workflow is a straight input -> LLM -> output pipeline.

    Attributes:
        name (str): The name of the assistant.
        api_key (str): The API key for OpenAI. If not provided, it tries to use the OPENAI_API_KEY environment variable.
        model (str): The name of the OpenAI model to use.
        system_message (str): The system message for the support LLM.
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="GuardrailSupportAssistant")
    type: str = Field(default="GuardrailSupportAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default="gpt-4o-mini")
    system_message: str = Field(default=DEFAULT_SUPPORT_SYSTEM_MESSAGE)

    @classmethod
    def builder(cls) -> "GuardrailSupportAssistantBuilder":
        """Return a builder for GuardrailSupportAssistant."""
        return GuardrailSupportAssistantBuilder(cls)

    def _construct_workflow(self) -> "GuardrailSupportAssistant":
        agent_input_topic = InputTopic(name="agent_input_topic")
        agent_output_topic = OutputTopic(name="agent_output_topic")

        # A single LLM node wrapped in guardrails: no pause channel, no
        # consumer router -- the hooks only transform the payload in flight.
        llm_node = (
            HookedNode.builder()
            .name("GuardrailLLMNode")
            .type("LLMNode")
            .subscribe(SubscriptionBuilder().subscribed_to(agent_input_topic).build())
            .tool(
                OpenAITool.builder()
                .name("SupportLLM")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.system_message)
                .build()
            )
            # PRE: mask PII before the LLM sees the input.
            .pre_tool_hook(RedactPIIHook())
            # POST: stamp the reply with a disclaimer.
            .post_tool_hook(DisclaimerHook())
            .publish_to(agent_output_topic)
            .build()
        )

        # Create a workflow and add the node
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("GuardrailChainWorkflow")
            .node(llm_node)
            .build()
        )

        return self


class GuardrailSupportAssistantBuilder(AssistantBaseBuilder[GuardrailSupportAssistant]):
    """Concrete builder for GuardrailSupportAssistant."""

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self

    def system_message(self, system_message: str) -> Self:
        self.kwargs["system_message"] = system_message
        return self
