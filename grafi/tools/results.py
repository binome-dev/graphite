"""A function's results, as the tools that call functions output them.

``FunctionTool`` and ``FunctionCallTool`` call functions of any kind, with
:func:`call`, and output their results, :func:`function_results`:

* A plain function, sync or async, has one result: what it returns.
* A generator, sync or async, streams: each string it yields reaches a
  streaming caller as a delta (see :mod:`grafi.runtime.deltas`), and its result
  is that text, joined. If it also yields other values, they are its results,
  and its text only streams.

Sync code runs in a worker thread, so a blocking function never stalls the
event loop: in the executor of the invocation's services, else in grafi's own
pool (see :class:`~grafi.runtime.execution_services.ExecutionServices`). A sync
generator runs whole in one thread, in one context, so what it holds across a
``yield`` stays valid. Sync code cannot be stopped midway: a cancellation waits
for the call, or the generator's step, running, and drops a call not started.
Sync code must not wait for the event loop, which may be waiting for it. A
result becomes text, or messages, with :func:`as_text` and :func:`as_messages`.
"""

import asyncio
import contextvars
import functools
import inspect
import os
import threading
import weakref
from concurrent.futures import Executor
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from typing import Callable
from typing import Generator
from typing import List
from typing import Optional
from typing import TypeVar

from pydantic_core import to_json

from grafi.common.async_lifecycle import INTERRUPT_OR_EXIT
from grafi.common.async_lifecycle import cancelling
from grafi.common.async_lifecycle import log_not_raised
from grafi.common.async_lifecycle import owned_iterator
from grafi.common.async_lifecycle import unexpected_cancellation
from grafi.common.async_lifecycle import wait_all
from grafi.common.models.message import Message
from grafi.common.models.message import Messages
from grafi.runtime.deltas import emit_delta
from grafi.runtime.execution_services import current_services

T = TypeVar("T")


def is_sync(function: Callable[..., Any]) -> bool:
    """Whether calling ``function`` runs it: neither a coroutine function nor
    a generator function, which return what runs later. A partial, or a
    wrapper (``functools.wraps``), is judged by the function it wraps."""
    while isinstance(function, functools.partial):
        function = function.func
    function = inspect.unwrap(function)
    return not (
        inspect.iscoroutinefunction(function)
        or inspect.isasyncgenfunction(function)
        or inspect.isgeneratorfunction(function)
    )


async def call(function: Callable[[], Any]) -> Any:
    """What ``function()`` returns, awaited if it is awaitable, and a generator
    unstarted. A sync function runs in a worker thread."""
    result = await in_thread(function) if is_sync(function) else function()
    return await result if inspect.isawaitable(result) else result


async def function_results(function: Callable[[], Any]) -> List[Any]:
    """The results of ``function()``, a function of any kind with its
    arguments bound: see this module."""
    result = await call(function)
    if inspect.isasyncgen(result):
        items = []
        async with owned_iterator(result) as stream:
            async for item in stream:
                if isinstance(item, str):
                    emit_delta(item)
                items.append(item)
    elif inspect.isgenerator(result):
        items = await _drained(result)
    else:
        return [result]
    text = [item for item in items if isinstance(item, str)]
    values = [item for item in items if not isinstance(item, str)]
    return values or (["".join(text)] if text else [])


async def _drained(generator: Generator[Any, Any, Any]) -> List[Any]:
    """What a sync generator yields, run whole in one worker thread, each
    string emitted as a delta as it comes. A cancellation stops it after its
    step running, and closes it there."""
    stop = threading.Event()

    def drain() -> List[Any]:
        items = []
        try:
            for item in generator:
                if isinstance(item, str):
                    emit_delta(item)  # Delivered on the loop, in order.
                items.append(item)
                if stop.is_set():
                    break
        finally:
            generator.close()
        return items

    return await in_thread(drain, stop)


async def in_thread(call: Callable[[], T], stop: Optional[threading.Event] = None) -> T:
    """``call()``, run in a worker thread in a copy of this context.

    A cancellation drops the call if it has not started. Sync code cannot be
    stopped midway, so a call that has started is waited for (``stop`` is set
    first, for a call that ends early when it is); then the cancellation is
    raised, unless the call raised an interrupt or exit, which outranks it;
    anything else it raised is logged.
    """
    job = _executor().submit(contextvars.copy_context().run, call)
    future = asyncio.wrap_future(job)
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError as cancelled:
        if future.done() and not cancelling():
            # Raised by the call itself, as by a cancelled future's result().
            raise unexpected_cancellation("A sync call was cancelled", cancelled)
        if not job.cancel():  # Started: waited for.
            if stop is not None:
                stop.set()
            await wait_all([future])
            error = None if future.cancelled() else future.exception()
            if isinstance(error, INTERRUPT_OR_EXIT):
                raise error
            if error is not None:
                log_not_raised(error, "its caller was cancelled")
        raise


# grafi's pools for sync code, one for each event loop running it.
_pools: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, ThreadPoolExecutor]"
_pools = weakref.WeakKeyDictionary()
if hasattr(os, "register_at_fork"):  # A forked process starts afresh.
    os.register_at_fork(after_in_child=_pools.clear)


def _executor() -> Executor:
    """Where sync code runs: the services' executor, else grafi's pool for this
    event loop, never asyncio's default executor, which also resolves host
    names: sync tools waiting there would hold up every connection the process
    opens. A pool for each loop, as asyncio's default executor is, lives as
    long as its loop."""
    executor = current_services().executor
    if executor is not None:
        return executor
    loop = asyncio.get_running_loop()
    pool = _pools.get(loop)
    if pool is None:
        pool = _pools[loop] = ThreadPoolExecutor(thread_name_prefix="grafi-sync")
    return pool


def as_text(value: Any) -> str:
    """``value`` as a message's text: a string as it is, anything else as JSON,
    or as its ``str()`` where JSON cannot hold it."""
    if isinstance(value, str):
        return value
    return to_json(value, fallback=str).decode()


def as_messages(value: Any, role: str = "assistant") -> Messages:
    """``value`` as a tool's output: messages as they are (so an empty list is
    no output), None as none, and anything else as one message from ``role``
    holding it as text."""
    if value is None:
        return []
    if isinstance(value, Message):
        return [value]
    if isinstance(value, list) and all(isinstance(item, Message) for item in value):
        return value
    return [Message.model_validate({"role": role, "content": as_text(value)})]
