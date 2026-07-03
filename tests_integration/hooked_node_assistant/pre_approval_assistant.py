import json
import os
from typing import Any
from typing import Dict
from typing import Optional
from typing import Self

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.assistants.assistant import Assistant
from grafi.assistants.assistant_base import AssistantBaseBuilder
from grafi.common.models.message import Message
from grafi.nodes.conditions import has_no_tool_call
from grafi.nodes.conditions import has_tool_call
from grafi.nodes.hooks.hitl_approval_hook import HITLApprovalHook
from grafi.nodes.hooks.hitl_approval_hook import ToolCallReasonHook
from grafi.nodes.hooks.hitl_approval_hook import has_tool_call_message
from grafi.nodes.hooks.tool_hook import ToolHook
from grafi.nodes.hooks.tool_hook import ToolHookFrame
from grafi.nodes.impl.hooked_node import HookedNode
from grafi.nodes.routing import ConsumerRouter
from grafi.nodes.routing import Decision
from grafi.nodes.routing import Stage
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.llms.impl.openai_tool import OpenAITool
from grafi.topics.expressions.subscription_builder import SubscriptionBuilder
from grafi.topics.topic_impl.in_workflow_input_topic import InWorkflowInputTopic
from grafi.topics.topic_impl.in_workflow_output_topic import InWorkflowOutputTopic
from grafi.topics.topic_impl.input_topic import InputTopic
from grafi.topics.topic_impl.output_topic import OutputTopic
from grafi.topics.topic_impl.topic import Topic
from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow

_DEFAULT_REFUND_LIMIT_USD = 500.0
_DEFAULT_SYSTEM_MESSAGE = (
    "You are a customer-service agent for an online store. When the user asks "
    "for a refund, call the refund tool with the order id and amount they gave. "
    "For anything else, answer directly without calling any tool. When a refund "
    "is declined -- by policy or by a human reviewer -- relay the decision to "
    "the customer and do NOT call the refund tool again. When you receive a "
    "refund confirmation, summarize it for the customer."
)


class SpendingLimitHook(ToolHook):
    """Policy screen: auto-deny refund calls whose amount exceeds the limit.

    Runs BEFORE the human gate in the pre-tool chain, so an over-limit refund
    is denied by policy without ever bothering a reviewer. The hook parses the
    proposed call's arguments; anything missing or unparseable PROCEEDs
    untouched (the policy only speaks when it can read an amount).
    """

    limit_usd: float = _DEFAULT_REFUND_LIMIT_USD

    async def invoke(self, frame: ToolHookFrame) -> ToolHookFrame:
        if not frame.messages:
            return frame
        tool_calls = frame.messages[-1].tool_calls
        if not tool_calls:
            return frame
        try:
            args = json.loads(tool_calls[0].function.arguments or "{}")
            amount = float(args["amount"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            # No readable amount -> not this policy's call to make.
            return frame
        if amount > self.limit_usd:
            frame.decision = Decision.DENY
            frame.messages = [
                Message(
                    role="assistant",
                    content=(
                        f"Refund denied by spending policy: the requested "
                        f"amount ${amount:.2f} exceeds the ${self.limit_usd:.2f} "
                        "limit, so the refund was not processed and cannot be "
                        "approved automatically."
                    ),
                )
            ]
        return frame

    def to_dict(self) -> Dict[str, Any]:
        return {"type": type(self).__name__, "limit_usd": self.limit_usd}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpendingLimitHook":
        return cls(limit_usd=float(data.get("limit_usd", _DEFAULT_REFUND_LIMIT_USD)))


class RefundApprovalAssistant(Assistant):
    """A refund agent with a policy chain in front of a human approval gate.

    The LLM node proposes refund tool calls (justified via ToolCallReasonHook)
    and routes them to the refund function node, whose PRE-tool chain runs two
    screens in order:

    1. SpendingLimitHook -- policy auto-denies over-limit refunds. The denial
       flows straight back to the LLM as a normal output; no human is asked.
    2. HITLApprovalHook -- in-limit refunds pause on the approval channel for
       a human verdict. The pause payload IS the proposal the human reviews.

    On resume, the consumer router classifies the verdict: a plain "approve"
    recovers the STORED proposal from the event store and runs the tool on it
    (what was approved is what runs); a denial reply skips the tool and flows
    back to the LLM, which explains the outcome to the customer.
    """

    oi_span_type: OpenInferenceSpanKindValues = Field(
        default=OpenInferenceSpanKindValues.AGENT
    )
    name: str = Field(default="RefundApprovalAssistant")
    type: str = Field(default="RefundApprovalAssistant")
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    model: str = Field(default="gpt-4o-mini")
    refund_tool: FunctionCallTool
    refund_limit: float = Field(default=_DEFAULT_REFUND_LIMIT_USD)
    system_message: str = Field(default=_DEFAULT_SYSTEM_MESSAGE)

    @classmethod
    def builder(cls) -> "RefundApprovalAssistantBuilder":
        """Return a builder for RefundApprovalAssistant."""
        return RefundApprovalAssistantBuilder(cls)

    def _construct_workflow(self) -> "RefundApprovalAssistant":
        agent_input_topic = InputTopic(name="agent_input_topic")
        agent_output_topic = OutputTopic(name="agent_output_topic")
        refund_call_topic = Topic(name="refund_call_topic")
        refund_result_topic = Topic(name="refund_result_topic")

        approval_response_topic = InWorkflowInputTopic(name="approval_response_topic")
        approval_request_topic = InWorkflowOutputTopic(
            name="approval_request_topic",
            paired_in_workflow_input_topic_names=[approval_response_topic.name],
        )

        llm_node = (
            HookedNode.builder()
            .name("RefundLLMNode")
            .type("LLMNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(agent_input_topic)
                .or_()
                .subscribed_to(refund_result_topic)
                .build()
            )
            .tool(
                OpenAITool.builder()
                .name("RefundLLM")
                .api_key(self.api_key)
                .model(self.model)
                .system_message(self.system_message)
                .build()
            )
            # Make the model justify each refund call (surfaced to the reviewer).
            .pre_tool_hook(ToolCallReasonHook())
            .publish_to(refund_call_topic, when=has_tool_call)
            .publish_to(agent_output_topic, when=has_no_tool_call)
            .build()
        )

        # The refund node screens each proposed call: the spending policy first
        # (auto-deny, no human involved), then the human gate LAST in the chain
        # so an in-limit call pauses on the approval channel.
        refund_node = (
            HookedNode.builder()
            .name("RefundFunctionNode")
            .type("FunctionCallNode")
            .subscribe(
                SubscriptionBuilder()
                .subscribed_to(refund_call_topic)
                .or_()
                .subscribed_to(approval_response_topic)
                .build()
            )
            .tool(self.refund_tool)
            .pre_tool_hook(SpendingLimitHook(limit_usd=self.refund_limit))
            .pre_tool_hook(HITLApprovalHook(gate_when=has_tool_call_message))
            .consumer_router(
                ConsumerRouter(pre_hitl_input=approval_response_topic.name)
            )
            .publish_to(refund_result_topic)
            .publish_to(approval_request_topic, from_stage=Stage.PRE_HOOK)
            .build()
        )

        # Create a workflow and add the nodes
        self.workflow = (
            EventDrivenWorkflow.builder()
            .name("RefundApprovalWorkflow")
            .node(llm_node)
            .node(refund_node)
            .build()
        )

        return self


class RefundApprovalAssistantBuilder(AssistantBaseBuilder[RefundApprovalAssistant]):
    """Concrete builder for RefundApprovalAssistant."""

    def api_key(self, api_key: str) -> Self:
        self.kwargs["api_key"] = api_key
        return self

    def model(self, model: str) -> Self:
        self.kwargs["model"] = model
        return self

    def refund_tool(self, refund_tool: FunctionCallTool) -> Self:
        self.kwargs["refund_tool"] = refund_tool
        return self

    def refund_limit(self, refund_limit: float) -> Self:
        self.kwargs["refund_limit"] = refund_limit
        return self

    def system_message(self, system_message: str) -> Self:
        self.kwargs["system_message"] = system_message
        return self
