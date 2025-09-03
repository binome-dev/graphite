"""
Event store and topic-related exception classes.
"""

from typing import Optional

from grafi.common.exceptions.base import GrafiError
from grafi.common.models.invoke_context import InvokeContext


class EventStoreError(GrafiError):
    """Raised when event store operations fail."""

    pass


class EventSerializationError(EventStoreError):
    """Raised when event serialization/deserialization fails."""

    pass


class EventPersistenceError(EventStoreError):
    """Raised when persisting events to storage fails."""

    pass


class TopicError(GrafiError):
    """Raised when topic pub/sub operations fail."""

    def __init__(
        self,
        topic_name: str,
        message: str,
        invoke_context: Optional[InvokeContext] = None,
        cause: Optional[Exception] = None,
        **kwargs,
    ):
        super().__init__(message, invoke_context, cause, **kwargs)
        self.topic_name = topic_name


class TopicSubscriptionError(TopicError):
    """Raised when topic subscription fails."""

    pass


class TopicPublicationError(TopicError):
    """Raised when publishing to a topic fails."""

    pass
