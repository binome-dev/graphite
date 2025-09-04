"""
Tool-related exception classes.
"""

from typing import Any
from typing import Optional

from grafi.common.exceptions.base import GrafiError
from grafi.common.models.invoke_context import InvokeContext


class ToolInvocationError(GrafiError):
    """Base class for tool invocation failures."""

    def __init__(
        self,
        tool_name: str,
        message: str,
        invoke_context: Optional[InvokeContext] = None,
        cause: Optional[Exception] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, invoke_context, cause, **kwargs)
        self.tool_name = tool_name


class LLMToolException(ToolInvocationError):
    """Raised when LLM tool operations fail."""

    def __init__(
        self,
        tool_name: str,
        model: Optional[str] = None,
        message: str = "LLM tool operation failed",
        invoke_context: Optional[InvokeContext] = None,
        cause: Optional[Exception] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(tool_name, message, invoke_context, cause, **kwargs)
        self.model = model
        self.type = "LLM"


class FunctionCallException(ToolInvocationError):
    """Raised when function call tool operations fail."""

    def __init__(
        self,
        tool_name: str,
        function_name: Optional[str] = None,
        message: str = "Function call operation failed",
        invoke_context: Optional[InvokeContext] = None,
        cause: Optional[Exception] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(tool_name, message, invoke_context, cause, **kwargs)
        self.function_name = function_name
        self.type = "FunctionCall"


class FunctionToolException(ToolInvocationError):
    """Raised when generic function tool operations fail."""

    def __init__(
        self,
        tool_name: str,
        operation: Optional[str] = None,
        message: str = "Function tool operation failed",
        invoke_context: Optional[InvokeContext] = None,
        cause: Optional[Exception] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(tool_name, message, invoke_context, cause, **kwargs)
        self.operation = operation
        self.type = "Function"
