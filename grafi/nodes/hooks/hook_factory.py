"""Reconstruct a tool hook from its serialized form (no pickle)."""

from typing import Any
from typing import Dict
from typing import Type

from grafi.nodes.hooks.hitl_approval_hook import HITLApprovalHook
from grafi.nodes.hooks.hitl_approval_hook import ToolCallReasonHook
from grafi.nodes.hooks.tool_hook import ToolHook

_HOOK_TYPES: Dict[str, Type[ToolHook]] = {
    ToolHook.__name__: ToolHook,
    HITLApprovalHook.__name__: HITLApprovalHook,
    ToolCallReasonHook.__name__: ToolCallReasonHook,
}


def hook_from_dict(data: Dict[str, Any]) -> ToolHook:
    """Dispatch on the serialized ``type`` to the matching hook class."""
    type_name = data.get("type", ToolHook.__name__)
    try:
        hook_cls = _HOOK_TYPES[type_name]
    except KeyError as e:
        raise ValueError(f"Unknown tool hook type: {type_name!r}") from e
    return hook_cls.from_dict(data)
