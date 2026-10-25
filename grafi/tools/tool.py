import inspect
from typing import Any
from typing import ClassVar
from typing import Dict
from typing import Optional
from typing import Self
from typing import Type
from typing import TypeVar

from openinference.semconv.trace import OpenInferenceSpanKindValues
from pydantic import Field

from grafi.common.legacy import warn_never_called
from grafi.common.manifest import Component
from grafi.common.models.base_builder import BaseBuilder
from grafi.common.models.default_id import default_id
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages


def _removed_methods(cls: type) -> Dict[str, str]:
    """The ``removed_methods`` of ``cls``, merged over its MRO."""
    removed: Dict[str, str] = {}
    for klass in reversed(cls.__mro__):
        removed.update(vars(klass).get("removed_methods", {}))
    return removed


class Tool(Component):
    """What a node runs: it turns messages into messages.

    ``invoke`` returns the tool's output, which its node publishes as one
    event; no messages, and the node publishes nothing. A tool that produces
    its output piece by piece, such as an LLM's tokens, can also stream the
    pieces to a caller with :func:`~grafi.runtime.deltas.emit_delta`; they are
    never published.
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

    # Methods grafi called in 0.0.36 and earlier and no longer does, by name,
    # with what replaced them: a subclass having one, its own or a mixin's, is
    # warned that grafi will not call it.
    removed_methods: ClassVar[Dict[str, str]] = {}

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        refuse_invoke_not_returning(
            cls,
            "a tool returns its output, its messages, and streams text with "
            "grafi.runtime.deltas.emit_delta()",
        )
        warn_never_called(cls, Tool, _removed_methods)

    async def invoke(
        self,
        invoke_context: InvokeContext,
        input_data: Messages,
    ) -> Messages:
        """The tool's output for ``input_data``."""
        raise NotImplementedError("Subclasses must implement this method.")


def refuse_invoke_not_returning(cls: type, returns: str) -> None:
    """Raise TypeError unless ``cls.invoke`` is a coroutine function: a
    component of grafi 0.0.36 and earlier yielded its output in batches."""
    try:
        invoke = inspect.unwrap(cls.invoke)  # type: ignore[attr-defined]
    except ValueError:
        return  # Wrappers that wrap each other; their calls will tell.
    if inspect.iscoroutinefunction(invoke):
        return
    how = "yields" if inspect.isasyncgenfunction(invoke) else "is not async def"
    raise TypeError(f"{cls.__name__}.invoke() {how}: {returns}.")


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
