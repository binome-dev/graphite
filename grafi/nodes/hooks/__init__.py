"""Tool hooks for the hooked node's internal pipeline.

Custom :class:`ToolHook` subclasses auto-register by class name on import, so
they round-trip through serialized manifests -- import the module defining a
custom hook before deserializing a workflow that uses it.
"""

from grafi.nodes.hooks.hitl_approval_hook import HITLApprovalHook
from grafi.nodes.hooks.hitl_approval_hook import ToolCallReasonHook
from grafi.nodes.hooks.hitl_approval_hook import has_tool_call_message
from grafi.nodes.hooks.hook_factory import hook_from_dict
from grafi.nodes.hooks.tool_hook import ToolHook
from grafi.nodes.hooks.tool_hook import ToolHookFrame
from grafi.nodes.hooks.tool_hook import known_hook_types
from grafi.nodes.hooks.tool_hook import resolve_hook_type

__all__ = [
    "HITLApprovalHook",
    "ToolCallReasonHook",
    "ToolHook",
    "ToolHookFrame",
    "has_tool_call_message",
    "hook_from_dict",
    "known_hook_types",
    "resolve_hook_type",
]
