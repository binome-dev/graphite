"""How a function's results are run and read: sync code in worker threads,
which a cancellation waits for, as it cannot be stopped midway."""

import asyncio
import contextvars
import functools
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from typing import List

import pytest
from pydantic import validate_call

from grafi.common.exceptions import LLMToolException
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import Delta
from grafi.runtime import deltas_to
from grafi.runtime import emit_delta
from grafi.runtime.execution_services import ExecutionServices
from grafi.runtime.execution_services import bind_services
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.results import as_messages
from grafi.tools.results import function_results
from grafi.tools.results import in_thread
from grafi.tools.results import is_sync

CONTEXT = InvokeContext(conversation_id="c", invoke_id="i", assistant_request_id="r")
_value: contextvars.ContextVar[str] = contextvars.ContextVar("value", default="")


@pytest.mark.asyncio
async def test_a_cancelled_sync_call_is_waited_for_then_cancelled():
    done: List[str] = []

    def slow() -> None:
        time.sleep(0.2)
        done.append("finished")

    task = asyncio.create_task(in_thread(slow))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()  # Still running in its thread: waited for.
    await asyncio.wait({task})
    assert task.cancelled() and done == ["finished"]


@pytest.mark.asyncio
async def test_a_sync_generator_keeps_its_thread_and_context_across_yields():
    threads: List[int] = []

    def gen() -> Any:
        token = _value.set("inside")
        for word in ("a", "b", "c"):
            threads.append(threading.get_ident())
            yield word
        assert _value.get() == "inside"
        _value.reset(token)  # In the context it was set in.

    results = await function_results(gen)
    assert results == ["abc"]
    assert len(set(threads)) == 1 and threading.get_ident() not in threads


@pytest.mark.asyncio
async def test_a_sync_generator_streams_its_text_before_its_results_return():
    def gen() -> Any:
        yield "a"
        yield "b"

    received: List[Delta] = []
    with deltas_to(received.append, "node"):
        results = await function_results(gen)
    # Every delta arrived before the results did: none is lost after the step.
    assert [delta.content for delta in received] == ["a", "b"]
    assert results == ["ab"]


@pytest.mark.asyncio
async def test_a_cancelled_sync_generator_stops_after_its_step_and_closes_in_its_thread():
    threads: List[int] = []
    steps: List[str] = []
    stepping = threading.Event()

    def gen() -> Any:
        threads.append(threading.get_ident())
        try:
            yield {"first": 1}
            stepping.set()
            time.sleep(0.2)  # The step running when the cancellation comes.
            steps.append("second")
            yield {"second": 2}
            steps.append("third")  # Never reached: it stops after its step.
            yield {"third": 3}
        finally:
            threads.append(threading.get_ident())

    task = asyncio.create_task(function_results(gen))
    await asyncio.to_thread(stepping.wait)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()  # The step running is waited for.
    await asyncio.wait({task})
    assert task.cancelled()
    assert steps == ["second"]
    # Closed in the thread it ran in, not on the loop.
    assert len(set(threads)) == 1 and threading.get_ident() not in threads


@pytest.mark.asyncio
async def test_sync_code_runs_in_grafis_pool_not_asyncios_default_executor():
    thread_names: List[str] = []

    def record() -> None:
        thread_names.append(threading.current_thread().name)

    def gen() -> Any:
        record()
        yield "x"

    await in_thread(record)
    await function_results(gen)
    # asyncio's default executor also resolves host names: sync tools waiting
    # there would hold up every connection the process opens.
    assert all(name.startswith("grafi-sync") for name in thread_names)


@pytest.mark.asyncio
async def test_sync_code_runs_in_the_services_executor_when_they_have_one():
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="app-pool")
    thread_names: List[str] = []

    def answer(city: str) -> str:
        """Answer."""
        thread_names.append(threading.current_thread().name)
        return city

    tool = FunctionCallTool.builder().function(answer).build()
    call = Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "answer", "arguments": '{"city": "Oslo"}'},
                }
            ],
        }
    )
    try:
        with bind_services(ExecutionServices(executor=executor)):
            [result] = await tool.invoke(CONTEXT, [call])
    finally:
        executor.shutdown()
    assert result.content == "Oslo"
    assert [name.split("_")[0] for name in thread_names] == ["app-pool"]


def _sync(x: int) -> int:
    return x


async def _async(x: int) -> int:
    return x


def _generator(x: int) -> Any:
    yield x


async def _async_generator(x: int) -> Any:
    yield x


@pytest.mark.parametrize(
    ("function", "sync"),
    [(_sync, True), (_async, False), (_generator, False), (_async_generator, False)],
)
def test_is_sync_judges_partials_and_wrappers_by_the_function_they_wrap(
    function: Any, sync: bool
) -> None:
    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    for wrapped in (
        function,
        functools.partial(function, 1),
        functools.partial(functools.partial(function), x=1),
        wrapper,
        validate_call(function),
        functools.partial(validate_call(function), x=1),
    ):
        assert is_sync(wrapped) is sync, wrapped


def test_a_list_of_messages_passes_as_it_is_and_an_empty_one_is_no_output():
    messages = [Message(role="user", content="a"), Message(role="user", content="b")]
    assert as_messages(messages) is messages
    assert as_messages([]) == []
    assert json.loads(as_messages([1, 2])[0].content) == [1, 2]


@pytest.mark.asyncio
async def test_emitting_inside_a_function_call_marks_the_deltas_as_the_calls():
    def report(city: str) -> str:
        """Report."""
        emit_delta(f"looking up {city}")  # In a worker thread.
        return "sunny"

    tool = FunctionCallTool.builder().function(report).build()
    call = Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "report", "arguments": '{"city": "Oslo"}'},
                }
            ],
        }
    )
    received: List[Delta] = []
    with deltas_to(received.append, "node"):
        [answer] = await tool.invoke(CONTEXT, [call])
        await asyncio.sleep(0)  # A thread's delta is delivered on the loop.
    assert answer.content == "sunny"
    assert received == [Delta("looking up Oslo", "node", tool_call_id="c1")]


@pytest.mark.asyncio
async def test_on_error_raise_keeps_a_tool_error_as_it_is():
    error = LLMToolException(tool_name="inner", message="model down")

    async def ask() -> str:
        """Ask."""
        raise error

    tool = FunctionCallTool.builder().function(ask).on_error("raise").build()
    call = Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "ask", "arguments": "{}"},
                }
            ],
        }
    )
    with pytest.raises(LLMToolException) as raised:
        await tool.invoke(CONTEXT, [call])
    assert raised.value is error  # Not wrapped again.


@pytest.mark.asyncio
async def test_a_cancelled_call_that_had_not_started_never_runs():
    worker = ThreadPoolExecutor(max_workers=1)  # Busy: the next call queues.
    ran: List[str] = []
    with bind_services(ExecutionServices(executor=worker)):
        busy = asyncio.create_task(in_thread(lambda: time.sleep(0.2)))
        queued = asyncio.create_task(in_thread(lambda: ran.append("queued")))
    await asyncio.sleep(0.05)
    queued.cancel()
    await asyncio.wait({queued})
    assert queued.cancelled() and not busy.done()  # Dropped at once.
    await busy
    await asyncio.sleep(0.05)
    assert ran == []
    worker.shutdown()


@pytest.mark.asyncio
async def test_a_call_cancelled_again_while_its_tool_cleans_up_is_not_abandoned():
    done: List[str] = []

    def slow() -> str:
        """Slow."""
        time.sleep(0.3)
        done.append("slow")
        return "slow"

    async def fail() -> None:
        """Fails."""
        await asyncio.sleep(0.02)
        raise ValueError("no luck")

    tool = (
        FunctionCallTool.builder()
        .function(slow)
        .function(fail)
        .on_error("raise")
        .build()
    )
    call = Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": n,
                    "type": "function",
                    "function": {"name": n, "arguments": "{}"},
                }
                for n in ("slow", "fail")
            ],
        }
    )

    async def answer() -> None:
        await tool.invoke(CONTEXT, [call])

    task = asyncio.create_task(answer())
    await asyncio.sleep(0.1)  # fail raised; slow is being waited for.
    for _ in range(3):
        task.cancel()
        await asyncio.sleep(0.01)
    assert not task.done()
    await asyncio.wait({task})
    assert done == ["slow"]


@pytest.mark.asyncio
async def test_a_call_raising_a_cancellation_of_its_own_fails_and_is_answered():
    from concurrent.futures import CancelledError

    def bridged() -> str:
        """Bridged."""
        raise CancelledError()  # As a cancelled future's result() does.

    tool = FunctionCallTool.builder().function(bridged).build()
    call = Message.model_validate(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "bridged", "arguments": "{}"},
                }
            ],
        }
    )
    [answer] = await tool.invoke(CONTEXT, [call])
    assert answer.content == "Error: RuntimeError: A sync call was cancelled"


@pytest.mark.asyncio
async def test_sync_code_may_wait_for_an_invocation_on_a_loop_of_its_own():
    """Sync calls running an invocation of their own, as a sync agent_call may,
    do not wait behind themselves for the workers they hold: each loop has a
    pool of its own."""
    calls = 40  # More than a pool's workers.

    def nested() -> str:
        return asyncio.run(in_thread(lambda: "inner"))

    results = await asyncio.wait_for(
        asyncio.gather(*(in_thread(nested) for _ in range(calls))), timeout=20
    )

    assert results == ["inner"] * calls


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork() is POSIX's")
def test_a_forked_process_runs_sync_code() -> None:
    """A pool's threads do not survive a fork, as in a server forking workers
    after a warm-up: the child's sync code runs in a pool of its own."""
    asyncio.run(in_thread(lambda: None))  # The parent's pool has a thread.
    pid = os.fork()
    if pid == 0:
        code = 1
        try:
            ran = asyncio.run(asyncio.wait_for(in_thread(lambda: 42), timeout=5))
            code = 0 if ran == 42 else 1
        finally:
            os._exit(code)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
