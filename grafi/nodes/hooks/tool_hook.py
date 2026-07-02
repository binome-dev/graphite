"""Tool hooks: pure transforms over the tool payload that may signal a pause.

A hook is ``frame -> frame`` with no topic knowledge. The base :class:`ToolHook`
is the identity passthrough used when a node declares no hook.

Every :class:`ToolHook` subclass auto-registers by class name when its module is
imported, so custom hooks round-trip through serialized workflow manifests
without any extra wiring (see :func:`resolve_hook_type`).
"""

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Type

from loguru import logger
from pydantic import BaseModel
from pydantic import ConfigDict

from grafi.common.models.function_spec import FunctionSpecs
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.nodes.routing import Decision


class ToolHookFrame(BaseModel):
    """The payload a hook transforms.

    Carries no ``stage``: ``invoke`` only ever runs on a fresh batch (a resume is
    classified by the consumer router, not by re-running ``invoke``).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    invoke_context: InvokeContext
    messages: List[Message]
    decision: Decision = Decision.PROCEED


# Registry of hook classes by name, consumed by ``hook_from_dict``. Populated
# automatically by ``ToolHook.__init_subclass__``.
_HOOK_REGISTRY: Dict[str, Type["ToolHook"]] = {}


def resolve_hook_type(type_name: str) -> Optional[Type["ToolHook"]]:
    """Look up a registered hook class by its serialized ``type`` name."""
    return _HOOK_REGISTRY.get(type_name)


def known_hook_types() -> List[str]:
    """Names of every registered hook class (for error messages)."""
    return sorted(_HOOK_REGISTRY)


class ToolHook(BaseModel):
    """Identity base hook: passthrough, no pause, no transform."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-register the subclass so ``hook_from_dict`` can reconstruct it."""
        super().__init_subclass__(**kwargs)
        existing = _HOOK_REGISTRY.get(cls.__name__)
        if existing is not None and existing is not cls:
            logger.warning(
                f"Tool hook class name '{cls.__name__}' is already registered by "
                f"{existing.__module__}; {cls.__module__} now shadows it for "
                "deserialization."
            )
        _HOOK_REGISTRY[cls.__name__] = cls

    @property
    def decides(self) -> bool:
        """Whether this hook may pause or transform output (vs the identity base).

        A non-deciding (identity) post-hook lets the node stream the tool output
        per chunk unchanged; a deciding one makes the node aggregate the stream
        first so the hook sees the whole batch.
        """
        return type(self) is not ToolHook

    async def invoke(self, frame: ToolHookFrame) -> ToolHookFrame:
        return frame

    def augment_spec(self, specs: FunctionSpecs) -> FunctionSpecs:
        """Transform the function specs linked onto an LLM node (identity here).

        Hooks that need the model to see extra/changed tool parameters override
        this (e.g. injecting a required ``tool_call_reason``). The workflow calls
        it through :meth:`NodeBase.spec_augmenters` at build time.
        """
        return specs

    def to_dict(self) -> Dict[str, Any]:
        return {"type": type(self).__name__}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolHook":
        return cls()


# The base class is not a subclass of itself; register it explicitly.
_HOOK_REGISTRY[ToolHook.__name__] = ToolHook
