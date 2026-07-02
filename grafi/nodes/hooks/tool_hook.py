"""Tool hooks: pure transforms over the tool payload that may signal a pause.

A hook is ``frame -> frame`` with no topic knowledge. The base :class:`ToolHook`
is the identity passthrough used when a node declares no hook.
"""

from typing import Any
from typing import Dict
from typing import List

from pydantic import BaseModel
from pydantic import ConfigDict

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


class ToolHook(BaseModel):
    """Identity base hook: passthrough, no pause, no transform."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

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

    def to_dict(self) -> Dict[str, Any]:
        return {"type": type(self).__name__}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolHook":
        return cls()
