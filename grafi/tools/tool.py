from typing import Any
from typing import ClassVar
from typing import Optional
from typing import Self
from typing import Type
from typing import TypeVar

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.manifest import Component
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen


class Tool(Component):
    """What a node runs: it turns messages into messages.

    ``invoke`` yields the tool's output in batches of messages, and each batch
    the node publishes as one event. A tool that produces its output piece by
    piece, such as an LLM's tokens, can also stream the pieces to a caller
    with :func:`~grafi.runtime.deltas.emit_delta`; they are never published.
    Plain functions need no subclass: see ``FunctionTool`` and
    ``FunctionCallTool``. A tool is saved and loaded as data, with its fields
    (see :mod:`grafi.common.manifest`).
    """

    manifest_kind: ClassVar[Optional[str]] = "Tool"

    tool_id: str = default_id
    name: Optional[str] = Field(default=None)
    type: Optional[str] = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues

    # The Command class a node runs this tool through, set by @use_command and
    # inherited by subclasses; None means the base Command.
    command_class: ClassVar[Optional[Type[Any]]] = None

    async def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:
        """Yield the tool's output for ``input_data``, in batches of messages."""
        yield []  # Too keep mypy happy
        raise NotImplementedError("Subclasses must implement this method.")


T_T = TypeVar("T_T", bound="Tool")  # the Tool subclass


class ToolBuilder(BaseBuilder[T_T]):
    """Inner builder class for Tool construction."""

    def name(self, name: str) -> Self:
        """Set the tool's display name.

        Args:
            name: Human-readable identifier for the tool.

        Returns:
            Self for method chaining.
        """
        self.kwargs["name"] = name
        return self

    def type(self, type_name: str) -> Self:
        """Set the tool's type identifier.

        Args:
            type_name: Type classification for the tool.

        Returns:
            Self for method chaining.
        """
        self.kwargs["type"] = type_name
        return self

    def oi_span_type(self, oi_span_type: OpenInferenceSpanKindValues) -> Self:
        """Set the OpenInference span type for observability.

        Args:
            oi_span_type: The span type for tracing (e.g., TOOL, LLM, CHAIN).

        Returns:
            Self for method chaining.
        """
        self.kwargs["oi_span_type"] = oi_span_type
        return self
