"""Reconstruct a tool hook from its serialized form (no pickle).

Dispatch is driven by the hook registry in :mod:`grafi.nodes.hooks.tool_hook`:
every :class:`ToolHook` subclass auto-registers on import, so custom hooks
round-trip through manifests as long as their module has been imported before
deserialization.
"""

from typing import Any
from typing import Dict

# Imported for their registration side effect: the built-in hooks must be in
# the registry even when only this factory module is imported.
from grafi.nodes.hooks.hitl_approval_hook import HITLApprovalHook  # noqa: F401
from grafi.nodes.hooks.hitl_approval_hook import ToolCallReasonHook  # noqa: F401
from grafi.nodes.hooks.tool_hook import ToolHook
from grafi.nodes.hooks.tool_hook import known_hook_types
from grafi.nodes.hooks.tool_hook import resolve_hook_type


def hook_from_dict(data: Dict[str, Any]) -> ToolHook:
    """Dispatch on the serialized ``type`` to the matching registered hook class."""
    type_name = data.get("type")
    if type_name is None:
        # Fail closed: every serialized hook carries "type"; a missing key means
        # a malformed manifest, and silently defaulting to the identity ToolHook
        # would drop an approval gate.
        raise ValueError(
            f"Serialized hook is missing its 'type' key: {data!r}. Regenerate "
            "the manifest from the current assistant."
        )
    hook_cls = resolve_hook_type(type_name)
    if hook_cls is None:
        raise ValueError(
            f"Unknown tool hook type: {type_name!r}. Known types: "
            f"{known_hook_types()}. Custom hooks register automatically when "
            "their module is imported -- import it before deserializing."
        )
    return hook_cls.from_dict(data)
