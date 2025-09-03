"""
Workflow and node-related exception classes.
"""

from typing import Optional

from grafi.common.exceptions.base import GrafiError
from grafi.common.models.invoke_context import InvokeContext


class WorkflowError(GrafiError):
    """Raised when workflow execution encounters an error."""

    pass


class NodeExecutionError(WorkflowError):
    """Raised when a node fails during execution."""

    def __init__(
        self,
        node_name: str,
        message: str,
        invoke_context: Optional[InvokeContext] = None,
        cause: Optional[Exception] = None,
        **kwargs,
    ):
        super().__init__(message, invoke_context, cause, **kwargs)
        self.node_name = node_name
