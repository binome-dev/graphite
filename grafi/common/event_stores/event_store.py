"""The event store: where a run's events are recorded, and read back."""

import inspect
from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import Collection
from typing import List
from typing import Optional
from typing import Sequence

from grafi.common.events.event import Event
from grafi.common.events.event import EventType
from grafi.common.events.event_codec import EventCodec
from grafi.common.events.event_codec import default_event_codec


class EventStore(ABC):
    """Stores and manages events."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Refuse a store whose history reads take no ``event_types``, which
        grafi passes: such a store was written before it did."""
        super().__init_subclass__(**kwargs)
        for name in ("get_agent_events", "get_conversation_events"):
            try:
                parameters = inspect.signature(getattr(cls, name)).parameters
            except (TypeError, ValueError):  # Not one inspect can read.
                continue
            by_keyword = (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
            if not any(
                (p.name == "event_types" and p.kind in by_keyword)
                or p.kind is p.VAR_KEYWORD
                for p in parameters.values()
            ):
                raise TypeError(
                    f"{cls.__name__}.{name}() takes no event_types by keyword, "
                    "as grafi passes it: add `*, event_types: "
                    "Optional[Collection[EventType]] = None`, the types to read, "
                    "None for all."
                )

    # How the store encodes and decodes events, so that it need not know their
    # classes. The default is shared by every store in the process, so
    # ``.register(...)`` on it affects them all; for a registry of its own, give
    # the store a copy: ``self.codec = default_event_codec.copy()``.
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
    async def get_agent_events(
        self,
        assistant_request_id: str,
        *,
        event_types: Optional[Collection[EventType]] = None,
    ) -> List[Event]:
        """The events of the request ``assistant_request_id``, oldest first
        (by timestamp, or as recorded); only those of ``event_types``, unless
        it is None. A reader needing an order of its own sorts them, as grafi
        sorts a topic's by offset."""

    @abstractmethod
    async def get_conversation_events(
        self,
        conversation_id: str,
        *,
        event_types: Optional[Collection[EventType]] = None,
    ) -> List[Event]:
        """The events of the conversation ``conversation_id``, oldest first
        (by timestamp, or as recorded); only those of ``event_types``, unless
        it is None."""

    @abstractmethod
    async def get_topic_events(self, name: str, offsets: List[int]) -> List[Event]: ...

    async def aclose(self) -> None:
        """Release what the store holds, such as a connection pool."""
