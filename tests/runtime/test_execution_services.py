"""Tests for ExecutionServices, current_services(), and bind_services()."""

import contextvars
import dataclasses
import threading
from types import SimpleNamespace

import pytest
from opentelemetry.trace import NoOpTracer

from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.runtime import execution_services
from grafi.runtime.execution_services import ErrorReporter
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services
from grafi.runtime.execution_services import current_services
from grafi.runtime.execution_services import set_default_services


def _services() -> ExecutionServices:
    return ExecutionServices(
        event_store=EventStoreInMemory(),
        tracer=NoOpTracer(),
        error_reporter=ErrorReporter(),
    )


class TestExecutionServicesShape:
    def test_is_frozen_dataclass_not_pydantic(self):
        services = _services()
        assert dataclasses.is_dataclass(services)
        # Not a Pydantic model: no serialization surface.
        assert not hasattr(services, "model_dump")
        assert not hasattr(services, "to_dict")

    def test_is_immutable(self):
        services = _services()
        with pytest.raises(dataclasses.FrozenInstanceError):
            services.event_store = EventStoreInMemory()  # type: ignore[misc]

    def test_repr_hides_dependencies(self):
        services = _services()
        text = repr(services)
        # repr must not leak the store/tracer/reporter (e.g. a db URL).
        assert "EventStoreInMemory" not in text
        assert "event_store" not in text
        assert text == "ExecutionServices()"


class TestProcessDefault:
    @pytest.fixture(autouse=True)
    def _no_default_yet(self, monkeypatch):
        monkeypatch.setattr(execution_services, "_default_services", None)
        monkeypatch.delenv("GRAFI_STRICT_SERVICES", raising=False)

    @staticmethod
    def _unbound() -> ExecutionServices:
        """current_services() outside any binding."""
        return contextvars.Context().run(current_services)

    def test_outside_a_binding_it_is_created_once_in_memory(self):
        services = self._unbound()
        assert services is self._unbound()
        assert isinstance(services.event_store, EventStoreInMemory)

    def test_set_default_services_sets_it(self):
        services = ExecutionServices()
        set_default_services(services)
        assert self._unbound() is services

    def test_a_binding_overrides_it(self, bound_services):
        assert current_services() is bound_services
        assert bound_services is not self._unbound()

    def test_a_log_sink_reading_the_services_does_not_deadlock(self, monkeypatch):
        # The creation warning reaches log sinks, which may read the services:
        # it must not be logged while the default's lock is held.
        monkeypatch.setattr(execution_services, "_default_lock", threading.Lock())
        reads_services = SimpleNamespace(
            warning=lambda *args: contextvars.Context().run(current_services)
        )
        monkeypatch.setattr(execution_services, "logger", reads_services)

        thread = threading.Thread(target=self._unbound, daemon=True)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive(), "creating the default deadlocked"

    def test_strict_mode_refuses_in_memory_services(self, monkeypatch):
        monkeypatch.setenv("GRAFI_STRICT_SERVICES", "true")
        with pytest.raises(RuntimeError, match="set_default_services"):
            self._unbound()

    def test_strict_mode_accepts_services_set_at_startup(self, monkeypatch):
        monkeypatch.setenv("GRAFI_STRICT_SERVICES", "true")
        services = ExecutionServices()
        set_default_services(services)
        assert self._unbound() is services


class _ClosingStore(EventStoreInMemory):
    closed = False

    async def aclose(self) -> None:
        self.closed = True


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_aclose_closes_the_event_store(self):
        store = _ClosingStore()
        await ExecutionServices(event_store=store).aclose()
        assert store.closed

    @pytest.mark.asyncio
    async def test_leaving_an_async_with_closes_the_event_store(self):
        store = _ClosingStore()
        async with ExecutionServices(event_store=store) as services:
            assert services.event_store is store and not store.closed
        assert store.closed

    @pytest.mark.asyncio
    async def test_leaving_on_an_error_still_closes_the_event_store(self):
        store = _ClosingStore()
        with pytest.raises(ValueError):
            async with ExecutionServices(event_store=store):
                raise ValueError("the application failed")
        assert store.closed


class TestBinding:
    def test_one_binding_cannot_be_entered_twice_at_once(self, bound_services):
        binding = bind_services(ExecutionServices())
        with binding:
            with pytest.raises(RuntimeError):
                with binding:
                    pass
        assert current_services() is bound_services

    def test_bind_makes_services_current(self):
        services = _services()
        with bind_services(services) as bound:
            assert bound is services
            assert current_services() is services

    def test_bind_nests_and_restores(self):
        outer = _services()
        inner = _services()
        with bind_services(outer):
            assert current_services() is outer
            with bind_services(inner):
                assert current_services() is inner
            # Inner scope restored the previous (outer) binding.
            assert current_services() is outer


def test_a_tracer_provider_given_as_the_tracer_is_refused() -> None:
    """As 0.0.36's setup_tracing() returned a tracer, and now the provider."""
    from opentelemetry.sdk.trace import TracerProvider

    with pytest.raises(TypeError, match="not a TracerProvider: setup_tracing"):
        ExecutionServices(tracer=TracerProvider())  # type: ignore[arg-type]
