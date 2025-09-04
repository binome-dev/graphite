"""
Grafi exception hierarchy for comprehensive error handling.
"""

from grafi.common.exceptions.base import (
    GrafiError,
    ValidationError,
)
from grafi.common.exceptions.duplicate_node_error import DuplicateNodeError
from grafi.common.exceptions.event_exceptions import (
    EventPersistenceError,
    EventSerializationError,
    EventStoreError,
    TopicError,
    TopicPublicationError,
    TopicSubscriptionError,
)
from grafi.common.exceptions.tool_exceptions import (
    FunctionCallException,
    FunctionToolException,
    LLMToolException,
    ToolInvocationError,
)
from grafi.common.exceptions.workflow_exceptions import (
    NodeExecutionError,
    WorkflowError,
)

__all__ = [
    # Base errors
    "GrafiError",
    "ValidationError",
    # Tool errors
    "ToolInvocationError",
    "LLMToolException",
    "FunctionCallException",
    "FunctionToolException",
    # Workflow errors
    "WorkflowError",
    "NodeExecutionError",
    # Event and topic errors
    "EventStoreError",
    "EventSerializationError",
    "EventPersistenceError",
    "TopicError",
    "TopicSubscriptionError",
    "TopicPublicationError",
    # Domain-specific errors
    "DuplicateNodeError",
]
