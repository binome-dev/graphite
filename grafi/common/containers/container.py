# container.py
import threading
from typing import Optional

from loguru import logger
from opentelemetry.trace import Tracer

from grafi.common.event_stores.event_store import EventStore
from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.common.instrumentations.tracing import TracingOptions
from grafi.common.instrumentations.tracing import setup_tracing


class SingletonMeta(type):
    _instances: dict[type, object] = {}
    _lock: threading.Lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        # Ensure thread-safe singleton creation
        with cls._lock:
            if cls not in cls._instances:
                cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class Container(metaclass=SingletonMeta):
    def __init__(self):
        # Per-instance attributes:
        self._event_store: Optional[EventStore] = None
        self._tracer: Optional[Tracer] = None

    @classmethod
    def register_event_store(cls, event_store: EventStore) -> None:
        """Override the default EventStore implementation."""
        if isinstance(event_store, EventStoreInMemory):
            logger.warning(
                "Using EventStoreInMemory. This is ONLY suitable for local testing but not for production."
            )
        cls()._event_store = event_store  # cls() always returns the singleton

    @classmethod
    def register_tracer(cls, tracer: Tracer) -> None:
        """Override the default Tracer implementation."""
        cls()._tracer = tracer

    @property
    def event_store(self) -> EventStore:
        if self._event_store is None:
            logger.warning(
                "Using EventStoreInMemory. This is ONLY suitable for local testing but not for production."
            )
            self._event_store = EventStoreInMemory()
        return self._event_store

    @property
    def tracer(self) -> Tracer:
        if self._tracer is None:
            self._tracer = setup_tracing(
                tracing_options=TracingOptions.AUTO,
                collector_endpoint="localhost",
                collector_port=4317,
                project_name="grafi-trace",
            )
        return self._tracer


container = Container()
