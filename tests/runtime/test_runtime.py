"""Tests for GrafiRuntime: request-scoped binding and propagation/isolation."""

import asyncio

import pytest

from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.runtime.execution_services import current_services
from grafi.runtime.runtime import GrafiRuntime


async def _read_services():
    """Read the bound services (used to probe a child task's context)."""
    return current_services()


class _ProbeAssistant:
    """Assistant-shaped probe whose invoke reports the services it observes.

    Yields ``(direct, in_task)`` -- the services seen directly and the services
    seen from inside an ``asyncio`` task it spawns -- so a test can assert the
    runtime bound them for the whole invocation, child tasks included.
    """

    async def invoke(self, input_data, is_sequential=False):
        direct = current_services()
        in_task = await asyncio.create_task(_read_services())
        yield (direct, in_task)


class TestDefaultRuntime:
    def test_default_runtime_uses_in_memory_store(self):
        runtime = GrafiRuntime()
        assert isinstance(runtime.services.event_store, EventStoreInMemory)

    def test_each_default_runtime_is_independent(self):
        assert GrafiRuntime() is not GrafiRuntime()
        # ... with distinct stores (no shared process-global state).
        assert (
            GrafiRuntime().services.event_store
            is not GrafiRuntime().services.event_store
        )


class TestRuntimeInvokeBinding:
    @pytest.mark.asyncio
    async def test_invoke_binds_services_for_the_invocation_and_child_tasks(self):
        runtime = GrafiRuntime()

        results = [item async for item in runtime.invoke(_ProbeAssistant(), None)]

        assert len(results) == 1
        direct, in_task = results[0]
        # The invocation and the task it spawned both see this runtime's services.
        assert direct is runtime.services
        assert in_task is runtime.services

    @pytest.mark.asyncio
    async def test_concurrent_invocations_are_isolated(self):
        rt_a = GrafiRuntime()
        rt_b = GrafiRuntime()

        async def _drain(rt):
            return [item async for item in rt.invoke(_ProbeAssistant(), None)][0]

        (a_direct, a_task), (b_direct, b_task) = await asyncio.gather(
            _drain(rt_a), _drain(rt_b)
        )

        # Each concurrent invocation saw its own runtime's services -- no cross-talk.
        assert a_direct is rt_a.services and a_task is rt_a.services
        assert b_direct is rt_b.services and b_task is rt_b.services
        assert rt_a.services is not rt_b.services
