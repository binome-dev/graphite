"""Unit tests for the node tool hooks (isolated, no engine)."""

import pytest
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import Function

from grafi.common.models.function_spec import FunctionSpec
from grafi.common.models.function_spec import ParameterSchema
from grafi.common.models.function_spec import ParametersSchema
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.hooks import HITLApprovalHook
from grafi.nodes.hooks import ToolHook
from grafi.nodes.hooks import ToolHookFrame
from grafi.nodes.hooks import has_tool_call_message
from grafi.nodes.hooks import hook_from_dict
from grafi.nodes.routing import Decision


def _spec() -> FunctionSpec:
    return FunctionSpec(
        name="f",
        description="d",
        parameters=ParametersSchema(
            properties={"x": ParameterSchema.model_validate({"type": "integer"})},
            required=["x"],
        ),
    )


def _ctx() -> InvokeContext:
    return InvokeContext(conversation_id="c", invoke_id="i", assistant_request_id="r")


def _frame(messages) -> ToolHookFrame:
    return ToolHookFrame(invoke_context=_ctx(), messages=messages)


def _tool_call_message() -> Message:
    return Message(
        role="assistant",
        tool_calls=[
            ChatCompletionMessageToolCall(
                id="c1", type="function", function=Function(name="f", arguments="{}")
            )
        ],
    )


class TestToolHook:
    @pytest.mark.asyncio
    async def test_identity_invoke_proceeds(self):
        hook = ToolHook()
        frame = _frame([Message(role="user", content="hi")])
        out = await hook.invoke(frame)
        assert out is frame
        assert out.decision is Decision.PROCEED


class TestHITLApprovalHook:
    @pytest.mark.asyncio
    async def test_invoke_requests_pause(self):
        out = await HITLApprovalHook().invoke(
            _frame([Message(role="user", content="hi")])
        )
        assert out.decision is Decision.REQUEST

    @pytest.mark.asyncio
    async def test_gate_when_pauses_only_on_match(self):
        hook = HITLApprovalHook(gate_when=has_tool_call_message)
        # a tool-call proposal pauses for review
        gated = await hook.invoke(_frame([_tool_call_message()]))
        assert gated.decision is Decision.REQUEST
        # a plain answer passes straight through
        passed = await hook.invoke(_frame([Message(role="assistant", content="hi")]))
        assert passed.decision is Decision.PROCEED

    def test_augment_spec_injects_required_reason(self):
        augmented = HITLApprovalHook().augment_spec([_spec()])
        params = augmented[0].parameters
        assert "tool_call_reason" in params.properties
        assert "tool_call_reason" in params.required

    def test_augment_spec_does_not_mutate_input(self):
        original = _spec()
        HITLApprovalHook().augment_spec([original])
        assert "tool_call_reason" not in original.parameters.properties

    def test_augment_spec_is_noop_when_disabled(self):
        hook = HITLApprovalHook(reason_guidance=None)
        spec = _spec()
        assert hook.augment_spec([spec])[0].parameters.properties.keys() == {"x"}


class TestHookSerialization:
    def test_tool_hook_round_trip(self):
        restored = hook_from_dict(ToolHook().to_dict())
        assert isinstance(restored, ToolHook)

    def test_hitl_hook_round_trip_default(self):
        restored = hook_from_dict(HITLApprovalHook().to_dict())
        assert isinstance(restored, HITLApprovalHook)
        assert restored.gate_when is None

    def test_hitl_hook_gate_when_round_trips_via_reference(self):
        hook = HITLApprovalHook(gate_when=has_tool_call_message)
        restored = hook_from_dict(hook.to_dict())
        assert isinstance(restored, HITLApprovalHook)
        assert restored.gate_when is has_tool_call_message

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown tool hook type"):
            hook_from_dict({"type": "NoSuchHook"})


class TestHookRegistry:
    def test_custom_hook_auto_registers_and_round_trips(self):
        class CustomAuditHook(ToolHook):
            note: str = "default"

            def to_dict(self):
                return {"type": type(self).__name__, "note": self.note}

            @classmethod
            def from_dict(cls, data):
                return cls(note=data.get("note", "default"))

        # Defining the class registered it; the factory reconstructs it.
        restored = hook_from_dict({"type": "CustomAuditHook", "note": "n1"})
        assert isinstance(restored, CustomAuditHook)
        assert restored.note == "n1"

    def test_unknown_type_error_is_actionable(self):
        with pytest.raises(ValueError) as err:
            hook_from_dict({"type": "NeverImportedHook"})
        message = str(err.value)
        # Names the type, lists known ones, and explains the import fix.
        assert "NeverImportedHook" in message
        assert "HITLApprovalHook" in message
        assert "import" in message.lower()
