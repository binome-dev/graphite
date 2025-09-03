"""
Grafi exception hierarchy for comprehensive error handling.
"""

from grafi.common.exceptions.base import (
    GrafiError,
    ValidationError,
)

from grafi.common.exceptions.event_exceptions import (
    EventStoreError,
    EventSerializationError,
    EventPersistenceError,
    TopicError,
    TopicPublicationError,
    TopicSubscriptionError,
)

from grafi.common.exceptions.tool_exceptions import (
    ToolInvocationError,
    LLMToolException,
    FunctionCallException,
    FunctionToolException,
)

from grafi.common.exceptions.workflow_exceptions import (
    WorkflowError,
    NodeExecutionError,
)

from grafi.common.exceptions.duplicate_node_error import DuplicateNodeError

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
