from typing import Any
from typing import ClassVar
from typing import Dict
from typing import Optional
from typing import Self
from typing import Type
from typing import TypeVar

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.models.message import MsgsAGen


class Tool(BaseModel):
    """What a node runs: it turns messages into messages.

    ``invoke`` yields the tool's output in batches of messages, and each batch
    the node publishes as one event. A tool that produces its output piece by
    piece, such as an LLM's tokens, can also stream the pieces to a caller
    with :func:`~grafi.runtime.deltas.emit_delta`; they are never published.
    Plain functions need no subclass: see ``FunctionTool`` and
    ``FunctionCallTool``.
    """

    tool_id: str = default_id
    name: Optional[str] = Field(default=None)
    type: Optional[str] = Field(default=None)
    oi_span_type: OpenInferenceSpanKindValues

    # The Command class a node runs this tool through, set by @use_command and
    # inherited by subclasses; None means the base Command.
    command_class: ClassVar[Optional[Type[Any]]] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> MsgsAGen:
        """Yield the tool's output for ``input_data``, in batches of messages."""
        yield []  # Too keep mypy happy
        raise NotImplementedError("Subclasses must implement this method.")

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the tool instance to a dictionary representation.

        Returns:
            Dict[str, Any]: A dictionary representation of the tool.
        """
        return {
            "class": self.__class__.__name__,
            "base_class": "Tool",
            "tool_id": self.tool_id,
            "name": self.name,
            "type": self.type,
            "oi_span_type": self.oi_span_type.value,
        }

    @classmethod
    async def from_dict(cls, data: Dict[str, Any]) -> "Tool":
        """
        Create a tool instance from a dictionary representation.

        Args:
            data (Dict[str, Any]): A dictionary representation of the tool.

        Returns:
            Tool: A tool instance created from the dictionary.
        """
        raise NotImplementedError("from_dict must be implemented in subclasses.")


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
