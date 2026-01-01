# container.py
import os
import threading
from typing import Any
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

    def __call__(cls: "SingletonMeta", *args: Any, **kwargs: Any) -> Any:
        # Ensure thread-safe singleton creation
        with cls._lock:
            if cls not in cls._instances:
                cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class Container(metaclass=SingletonMeta):
    def __init__(self) -> None:
        # Per-instance attributes:
        self._event_store: Optional[EventStore] = None
        self._tracer: Optional[Tracer] = None
        # Lock for thread-safe lazy initialization of properties
        self._init_lock: threading.Lock = threading.Lock()

    def register_event_store(self, event_store: EventStore) -> None:
        """Override the default EventStore implementation."""
        with self._init_lock:
            if isinstance(event_store, EventStoreInMemory):
                logger.warning(
                    "Using EventStoreInMemory. This is ONLY suitable for local testing but not for production."
                )
            self._event_store = event_store

    def register_tracer(self, tracer: Tracer) -> None:
        """Override the default Tracer implementation."""
        with self._init_lock:
            self._tracer = tracer

    @property
    def event_store(self) -> EventStore:
        # Fast path: already initialized
        if self._event_store is not None:
            return self._event_store
        # Slow path: initialize with lock (double-checked locking)
        with self._init_lock:
            if self._event_store is None:
                logger.warning(
                    "Using EventStoreInMemory. This is ONLY suitable for local testing but not for production."
                )
                self._event_store = EventStoreInMemory()
            return self._event_store

    @property
    def tracer(self) -> Tracer:
        # Fast path: already initialized
        if self._tracer is not None:
            return self._tracer
        # Slow path: initialize with lock (double-checked locking)
        with self._init_lock:
            if self._tracer is None:
                # Use environment variables with sensible defaults
                endpoint = os.getenv("OTEL_COLLECTOR_ENDPOINT", "localhost")
                port = int(os.getenv("OTEL_COLLECTOR_PORT", "4317"))
                project = os.getenv("GRAFI_PROJECT_NAME", "grafi-trace")
                self._tracer = setup_tracing(
                    tracing_options=TracingOptions.AUTO,
                    collector_endpoint=endpoint,
                    collector_port=port,
                    project_name=project,
                )
            return self._tracer


container: Container = Container()
