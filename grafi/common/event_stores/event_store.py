"""The event store: where a run's events are recorded, and read back."""

from abc import ABC
from abc import abstractmethod
from typing import List
from typing import Optional
from typing import Sequence

from grafi.common.events.event import Event
from grafi.common.events.event_codec import EventCodec
from grafi.common.events.event_codec import default_event_codec


class EventStore(ABC):
    """Stores and manages events."""

    # How the store encodes and decodes events, so that it need not know their
    # classes. The default is shared by every store in the process, so
    # ``.register(...)`` on it affects them all; for a registry of its own, give
    # the store another: ``store.codec = EventCodec({...})``.
    codec: EventCodec = default_event_codec

    @abstractmethod
    async def record_event(self, event: Event) -> None: ...

    @abstractmethod
    async def record_events(self, events: Sequence[Event]) -> None:
        """Record a batch atomically: all of its events, or none.

        A workflow writes the consumptions and publications of the steps that
        finish together as one batch; a step only partly written could not be
        resumed correctly.
        """

    @abstractmethod
    async def clear_events(self) -> None: ...

    @abstractmethod
    async def get_events(self) -> List[Event]: ...

    @abstractmethod
    async def get_event(self, event_id: str) -> Optional[Event]: ...

    @abstractmethod
    async def get_agent_events(self, assistant_request_id: str) -> List[Event]: ...

    @abstractmethod
    async def get_conversation_events(self, conversation_id: str) -> List[Event]: ...

    @abstractmethod
    async def get_topic_events(self, name: str, offsets: List[int]) -> List[Event]: ...

    async def aclose(self) -> None:
        """Release what the store holds, such as a connection pool."""
