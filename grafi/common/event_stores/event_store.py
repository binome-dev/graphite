"""Module for storing and managing events with optional file logging."""

from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence

from grafi.common.events.event import Event
from grafi.common.events.event_codec import EventCodec
from grafi.common.events.event_codec import default_event_codec


class EventStore(ABC):
    """Stores and manages events."""

    # Decoder for stored event dicts. Persistence backends delegate decoding to
    # the codec instead of knowing concrete event classes; override per instance
    # to register additional event types without editing this class.
    _codec: EventCodec = default_event_codec

    @abstractmethod
    async def record_event(self, event: Event) -> None: ...

    @abstractmethod
    async def record_events(self, events: Sequence[Event]) -> None: ...

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

    def _create_event_from_dict(self, event_dict: Dict[str, Any]) -> Optional[Event]:
        """Decode a stored event dict into an :class:`Event` via the codec.

        Kept as a thin delegate for backends (and tests) that decode persisted
        rows; the registry and error policy live in :class:`EventCodec`.
        """
        return self._codec.decode(event_dict)
