"""How a function's results are run and read: sync code in worker threads,
which a cancellation waits for, as it cannot be stopped midway."""

import asyncio
import contextvars
import json
import threading
import time
from typing import Any
from typing import List

import pytest

from grafi.common.exceptions import LLMToolException
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.runtime import Delta
from grafi.runtime import deltas_to
from grafi.runtime import emit_delta
from grafi.tools.function_calls.function_call_tool import FunctionCallTool
from grafi.tools.results import as_messages
from grafi.tools.results import function_results
from grafi.tools.results import in_thread

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

    results = [result async for result in function_results(gen)]
    assert results == ["abc"]
    assert len(set(threads)) == 1 and threading.get_ident() not in threads


@pytest.mark.asyncio
async def test_a_sync_generator_closed_early_is_closed_in_its_thread():
    closed_in: List[int] = []

    def gen() -> Any:
        try:
            yield {"first": 1}
            yield {"second": 2}
        finally:
            closed_in.append(threading.get_ident())

    results = function_results(gen)
    assert await anext(results) == {"first": 1}
    await results.aclose()
    assert closed_in and closed_in[0] != threading.get_ident()


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
        [[answer]] = [batch async for batch in tool.invoke(CONTEXT, [call])]
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
        [batch async for batch in tool.invoke(CONTEXT, [call])]
    assert raised.value is error  # Not wrapped again.


@pytest.mark.asyncio
async def test_a_cancelled_call_that_had_not_started_never_runs():
    from concurrent.futures import ThreadPoolExecutor

    worker = ThreadPoolExecutor(max_workers=1)  # Busy: the next call queues.
    ran: List[str] = []
    busy = asyncio.create_task(in_thread(lambda: time.sleep(0.2), worker))
    queued = asyncio.create_task(in_thread(lambda: ran.append("queued"), worker))
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
        [batch async for batch in tool.invoke(CONTEXT, [call])]

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
    [[answer]] = [batch async for batch in tool.invoke(CONTEXT, [call])]
    assert answer.content == "Error: RuntimeError: A sync call was cancelled"
