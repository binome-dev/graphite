"""Tests for GrafiRuntime: request-scoped binding and propagation/isolation."""

import asyncio
import gc
from typing import Any
from typing import AsyncIterator

import pytest

from grafi.common.event_stores.event_store_in_memory import EventStoreInMemory
from grafi.runtime.execution_services import ExecutionServices
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

    @pytest.mark.asyncio
    async def test_binding_released_after_close(self, bound_services):
        # A distinct runtime from the test's autouse-bound services.
        rt = GrafiRuntime()
        assert rt.services is not bound_services

        agen = rt.invoke(_ProbeAssistant(), None)
        direct, _ = await agen.__anext__()
        # The runtime's services are bound while the stream is iterated...
        assert direct is rt.services
        # ...and the prior (outer) binding is restored once it is closed.
        await agen.aclose()
        assert current_services() is bound_services

    @pytest.mark.asyncio
    async def test_the_callers_binding_holds_between_reads(
        self, bound_services: ExecutionServices
    ) -> None:
        # Regression: the runtime bound its services in the caller's context
        # for as long as the stream was open, as a generator's body runs in
        # the context of whoever iterates it.
        rt = GrafiRuntime()
        agen = rt.invoke(_ProbeAssistant(), None)
        direct, in_task = await agen.__anext__()
        assert direct is rt.services and in_task is rt.services
        assert current_services() is bound_services
        await agen.aclose()

    @pytest.mark.asyncio
    async def test_an_abandoned_stream_leaves_the_callers_binding(
        self, bound_services: ExecutionServices
    ) -> None:
        # Regression: a stream left open was closed from another task, which
        # could not reset the binding it had left in the caller's context.
        closed: list[ExecutionServices] = []

        class _ClosingProbe(_ProbeAssistant):
            async def invoke(
                self, input_data: Any, is_sequential: bool = False
            ) -> AsyncIterator[tuple[ExecutionServices, None]]:
                try:
                    yield (current_services(), None)
                finally:
                    closed.append(current_services())

        rt = GrafiRuntime()
        agen = rt.invoke(_ClosingProbe(), None)
        await agen.__anext__()
        del agen
        gc.collect()
        async with asyncio.timeout(5):
            while not closed:  # The loop closes the abandoned stream.
                await asyncio.sleep(0)
        assert closed == [rt.services]  # Closed with the runtime's services.
        assert current_services() is bound_services

    @pytest.mark.asyncio
    async def test_a_stream_closed_from_another_task_does_not_fail(self) -> None:
        # Regression: closing a stream from another task (as the loop does for
        # an abandoned one) reset the binding in the wrong context.
        rt = GrafiRuntime()
        agen = rt.invoke(_ProbeAssistant(), None)
        await agen.__anext__()
        await asyncio.create_task(agen.aclose())


def test_a_stream_left_open_at_loop_shutdown_records_no_false_failure() -> None:
    # Regression: as the loop shut down it closed every open async generator
    # at once, the closing helpers too, in the middle of their own exits; the
    # clash ("athrow(): asynchronous generator is already running") was
    # recorded as the assistant's failure.
    from grafi.assistants.assistant import Assistant
    from grafi.common.events.component_base import FailedEvent
    from grafi.runtime.execution_services import ExecutionServices
    from grafi.topics.expressions.topic_expression import TopicExpr
    from grafi.topics.topic_impl.input_topic import InputTopic
    from grafi.topics.topic_impl.output_topic import OutputTopic
    from grafi.workflows.impl.event_driven_workflow import EventDrivenWorkflow
    from tests_integration.async_execution.support import EchoTool
    from tests_integration.async_execution.support import input_event
    from tests_integration.async_execution.support import make_node

    node = make_node(
        "echo",
        EchoTool(),
        TopicExpr(topic=InputTopic(name="input")),
        OutputTopic(name="output"),
    )
    assistant = Assistant(
        name="assistant", workflow=EventDrivenWorkflow.builder().node(node).build()
    )
    store = EventStoreInMemory()
    runtime = GrafiRuntime(ExecutionServices(event_store=store))
    left_open: list[Any] = []

    async def main() -> None:
        stream = runtime.invoke(assistant, input_event())
        await anext(stream)
        left_open.append(stream)  # Still open as asyncio.run() shuts down.

    asyncio.run(main())
    events = asyncio.run(store.get_events())
    # The shutdown cancels the run's tasks, which the run records as its
    # failure; no component records the helpers' clash as its own.
    errors = [event.error for event in events if isinstance(event, FailedEvent)]
    assert not [error for error in errors if "generator" in error]
