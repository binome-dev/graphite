"""A function's results, as the tools that call functions output them.

``FunctionTool`` and ``FunctionCallTool`` call functions of any kind:

* A plain function, sync or async, has one result: what it returns.
* A generator, sync or async, streams: each string it yields reaches a
  streaming caller as a delta (see :mod:`grafi.runtime.deltas`), and its result
  is that text, joined. If it also yields other values, they are its results,
  and its text only streams.

Sync code runs in a worker thread, so a blocking function never stalls the
event loop; a sync generator runs in a thread of its own, in one context, so
what it holds across a ``yield`` stays valid. Sync code cannot be stopped
midway: a cancellation waits for the call or step running to return, and drops
one not started. Sync code must not wait for the event loop, which may be
waiting for it. A result
becomes text, or messages, with :func:`as_text` and :func:`as_messages`.
"""

import asyncio
import contextvars
import functools
import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from typing import AsyncIterator
from typing import Callable
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

T = TypeVar("T")
_END = object()


def is_sync(function: Callable[..., Any]) -> bool:
    """Whether calling ``function`` runs it: neither a coroutine function nor
    a generator function, which return what runs later."""
    return not (
        inspect.iscoroutinefunction(function)
        or inspect.isasyncgenfunction(function)
        or inspect.isgeneratorfunction(function)
    )


class _Job:
    """A sync call for a worker thread, which can be dropped until it starts."""

    def __init__(self, call: Callable[[], T], context: contextvars.Context) -> None:
        self._call = call
        self._context = context
        self._lock = threading.Lock()
        self._started = self._dropped = False

    def __call__(self) -> Any:
        with self._lock:
            if self._dropped:
                return None
            self._started = True
        return self._context.run(self._call)

    def drop(self) -> bool:
        """Drop the call unless it started; whether it was dropped."""
        with self._lock:
            self._dropped = not self._started
            return self._dropped


async def in_thread(
    call: Callable[[], T],
    executor: Optional[ThreadPoolExecutor] = None,
    droppable: bool = True,
) -> T:
    """``call()``, run in a worker thread in a copy of this context.

    A cancellation drops the call if it has not started, and it is
    ``droppable``. Sync code cannot be stopped midway, so a call that has
    started is waited for, then the cancellation is raised, unless the call
    raised an interrupt or exit, which outranks it; anything else it raised is
    logged.
    """
    loop = asyncio.get_running_loop()
    job = _Job(call, contextvars.copy_context())
    future = loop.run_in_executor(executor, job)
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError as cancelled:
        if future.done() and not cancelling():
            # Raised by the call itself, as by a cancelled future's result().
            raise unexpected_cancellation("A sync call was cancelled", cancelled)
        if not (droppable and job.drop()):
            await wait_all([future])
            error = None if future.cancelled() else future.exception()
            if isinstance(error, INTERRUPT_OR_EXIT):
                raise error
            if error is not None:
                log_not_raised(error, "its caller was cancelled")
        raise


async def function_results(call: Callable[[], Any]) -> AsyncIterator[Any]:
    """The results of ``call()``, a function with its arguments bound."""
    result = await in_thread(call) if is_sync(call) else call()
    if inspect.isawaitable(result):
        result = await result
    if not (inspect.isasyncgen(result) or inspect.isgenerator(result)):
        yield result
        return
    text: List[str] = []
    values = False
    async with owned_iterator(_items(result)) as items:
        async for item in items:
            if isinstance(item, str):
                emit_delta(item)
                text.append(item)
            else:
                values = True
                yield item
    if text and not values:
        yield "".join(text)


async def _items(generator: Any) -> AsyncIterator[Any]:
    """What a sync or async generator yields. A sync one runs in a thread of
    its own, in one context, and is closed there."""
    if inspect.isasyncgen(generator):
        async with owned_iterator(generator) as items:
            async for item in items:
                yield item
        return
    thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="grafi-generator")
    context = contextvars.copy_context()
    step = functools.partial(context.run, next, generator, _END)
    try:
        while (item := await in_thread(step, thread)) is not _END:
            yield item
    finally:
        try:
            close = functools.partial(context.run, generator.close)
            await in_thread(close, thread, droppable=False)
        finally:
            thread.shutdown(wait=False)


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
