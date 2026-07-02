"""HITL hooks: pause for approval, and make the model justify its tool calls."""

from typing import Any
from typing import Callable
from typing import Dict
from typing import Optional

from grafi.common.callable_ref import deserialize_callable
from grafi.common.callable_ref import serialize_callable
from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.message import Messages
from grafi.nodes.hooks.tool_hook import ToolHook
from grafi.nodes.hooks.tool_hook import ToolHookFrame
from grafi.nodes.routing import Decision

# Reserved tool-call argument the framework injects so a gated call carries a
# human-readable reason for review. The hooked node strips it before the
# function runs (it is not a real parameter). See
# grafi.nodes.impl.hooked_node._strip_reserved_tool_args.
TOOL_CALL_REASON_KEY = "tool_call_reason"
_DEFAULT_GUIDANCE = (
    "Your own one-sentence justification for making this call, derived from the "
    "user's request. Always fill this in yourself; never ask the user for it."
)


def has_tool_call_message(messages: Messages) -> bool:
    """Gate predicate: True when the last message proposes a tool call.

    Used as ``HITLApprovalHook(gate_when=has_tool_call_message)`` so a post-hook
    pauses only tool-call proposals and lets plain text answers through.
    """
    return bool(messages) and messages[-1].tool_calls is not None


def inject_tool_call_reason(specs: FunctionSpecs, guidance: str) -> FunctionSpecs:
    """Return specs with a required ``tool_call_reason`` parameter added.

    Does not mutate the input specs. Used by hooks that want the model to
    justify a tool call destined for human review.
    """
    augmented: FunctionSpecs = []
    for spec in specs:
        new_spec = spec.model_copy(deep=True)
        new_spec.parameters.properties[TOOL_CALL_REASON_KEY] = (
            ParameterSchema.model_validate({"type": "string", "description": guidance})
        )
        if TOOL_CALL_REASON_KEY not in new_spec.parameters.required:
            new_spec.parameters.required.append(TOOL_CALL_REASON_KEY)
        augmented.append(new_spec)
    return augmented


class ToolCallReasonHook(ToolHook):
    """Augment-only hook: make the model justify its tool calls (no pause).

    On an LLM node, :meth:`augment_spec` injects a required ``tool_call_reason``
    parameter so the model explains *why* it is calling a tool; the reason rides
    in the call (surfaced to a downstream reviewer) and the node strips it before
    the function runs. Unlike :class:`HITLApprovalHook` it never pauses -- pair
    it with a consumer-router verdict gate on the function node.
    """

    reason_guidance: str = _DEFAULT_GUIDANCE

    def augment_spec(self, specs: FunctionSpecs) -> FunctionSpecs:
        return inject_tool_call_reason(specs, self.reason_guidance)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": type(self).__name__, "reason_guidance": self.reason_guidance}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCallReasonHook":
        return cls(reason_guidance=data.get("reason_guidance", _DEFAULT_GUIDANCE))


class HITLApprovalHook(ToolHook):
    """Requests a human-approval pause, and (optionally) makes the model justify.

    As a pre-hook it pauses before the tool runs; as a post-hook it pauses for
    review of the tool output. ``gate_when`` (optional) restricts the pause to
    matching batches (e.g. only tool-call proposals); the default pauses every
    batch. When ``reason_guidance`` is set (the default), :meth:`augment_spec`
    injects a required ``tool_call_reason`` parameter (set it to None to disable).
    """

    gate_when: Optional[Callable[[Messages], bool]] = None
    reason_guidance: Optional[str] = _DEFAULT_GUIDANCE

    async def invoke(self, frame: ToolHookFrame) -> ToolHookFrame:
        if self.gate_when is None or self.gate_when(frame.messages):
            frame.decision = Decision.REQUEST
        return frame

    def augment_spec(self, specs: FunctionSpecs) -> FunctionSpecs:
        if not self.reason_guidance:
            return specs
        return inject_tool_call_reason(specs, self.reason_guidance)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "type": type(self).__name__,
            "reason_guidance": self.reason_guidance,
        }
        if self.gate_when is not None:
            data["gate_when"] = serialize_callable(self.gate_when)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HITLApprovalHook":
        raw = data.get("gate_when")
        gate_when = (
            deserialize_callable(raw, context="HITLApprovalHook gate_when")
            if raw
            else None
        )
        return cls(
            gate_when=gate_when,
            reason_guidance=data.get("reason_guidance", _DEFAULT_GUIDANCE),
        )
