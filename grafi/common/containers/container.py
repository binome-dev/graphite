from typing import Optional
from typing import Type

from grafi.common.event_stores.event_store import EventStore
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory


class Container:
    _instance = None
    _event_store: Optional[EventStore] = None
    _event_store_class: Type[EventStore] = EventStoreInMemory

    def __new__(cls) -> "Container":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._event_store = cls._event_store_class()
        return cls._instance

    @classmethod
    def register_event_store(
        cls, event_store_class: Type[EventStore], event_store: EventStore
    ) -> None:
        """Register a different EventStore implementation"""
        cls._event_store_class = event_store_class
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._event_store = cls._event_store_class()
        cls._instance._event_store = event_store

    @property
    def event_store(self) -> EventStore:
        return self._event_store


container = Container()
