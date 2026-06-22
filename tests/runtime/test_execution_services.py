"""Tests for ExecutionServices, current_services(), and bind_services()."""

import contextvars
import dataclasses

import pytest
from opentelemetry.trace import NoOpTracer

from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.runtime.execution_services import ErrorReporter
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services
from grafi.runtime.execution_services import current_services


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


class TestBinding:
    def test_current_services_raises_outside_scope(self):
        # A fresh context has the ContextVar at its default (None).
        ctx = contextvars.Context()

        def _call() -> None:
            with pytest.raises(RuntimeError):
                current_services()

        ctx.run(_call)

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
