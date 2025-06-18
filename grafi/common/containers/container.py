from typing import Optional
from typing import Type

from opentelemetry.trace import Tracer

from grafi.common.event_stores.event_store import EventStore
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.instrumentations.tracing import TracingOptions
from grafi.common.instrumentations.tracing import setup_tracing


class Container:
    _instance = None
    _event_store: Optional[EventStore] = None
    _event_store_class: Type[EventStore] = EventStoreInMemory

    _tracer: Optional[Tracer] = None

    def __new__(cls) -> "Container":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._event_store = cls._event_store_class()
            cls._instance._tracer = setup_tracing(
                tracing_options=TracingOptions.AUTO,
                collector_endpoint="localhost",
                collector_port=4317,
                project_name="grafi-trace",
            )
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

    @classmethod
    def register_tracer(cls, tracer: Tracer) -> None:
        """Register a different EventStore implementation"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._event_store = cls._event_store_class()
            cls._instance._tracer = tracer
        cls._instance._tracer = tracer

    @property
    def event_store(self) -> EventStore:
        return self._event_store

    @property
    def tracer(self) -> Tracer:
        return self._tracer


container = Container()
