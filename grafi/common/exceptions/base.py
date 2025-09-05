"""
Base exception classes for the Grafi framework.
"""

import time
from typing import Any
from typing import Dict
from typing import Optional

from grafi.common.models.invoke_context import InvokeContext


class GrafiError(Exception):
    """Base exception for all Grafi framework errors.

    Attributes:
        message: Human-readable error message
        context: Additional context information about the error
        cause: The underlying exception that caused this error
        timestamp: When the error occurred
        severity: Error severity level
    """

    def __init__(
        self,
        message: str,
        invoke_context: Optional[InvokeContext] = None,
        cause: Optional[Exception] = None,
        severity: str = "ERROR",
    ):
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.invoke_context = invoke_context
        self.timestamp = time.time()
        self.severity = severity

    def __str__(self) -> str:
        base_msg = f"[{self.severity}] {self.message}"
        if self.invoke_context:
            base_msg = f"{base_msg} [Invoke Context: {self.invoke_context}]"
        if self.cause:
            base_msg = f"{base_msg} [Caused by: {type(self.cause).__name__}: {str(self.cause)}]"
        return base_msg

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for structured logging."""
        return {
            "error_type": type(self).__name__,
            "message": self.message,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "cause": str(self.cause) if self.cause else None,
            "invoke_context": (
                self.invoke_context.model_dump() if self.invoke_context else None
            ),
        }


class ValidationError(GrafiError):
    """Raised when input validation fails."""

    pass
