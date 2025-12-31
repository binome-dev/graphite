import asyncio
from typing import AsyncGenerator
from typing import Optional
from typing import TypeVar

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)


_SENTINEL = object()


T = TypeVar("T")


class AsyncResult:
    """
    Wraps one of:
      - an async generator
      - an awaitable (coroutine / Future / Task)
      - a plain sync value

    Behaviors:
      - `async for x in wrapper:` yields stream elements.
      - `await wrapper`:
          * if source is an async generator -> returns a `list` of all items
          * if source is awaitable or plain value -> returns that single value

    Notes:
      - The wrapper internally starts a producer task on first use, buffering
        items in a queue and mirroring them into a list so that `await` and
        `async for` can be used in any order (but data is still consumed once).
      - If you only ever need iteration OR a single await, you still get the
        expected behavior without extra overhead.
    """

    def __init__(self, source: AsyncGenerator[ConsumeFromTopicEvent, None]):
        self._source = source

        self._queue: asyncio.Queue[ConsumeFromTopicEvent] = asyncio.Queue()
        self._items: list[ConsumeFromTopicEvent] = []
        self._done = asyncio.Event()
        self._started = False
        self._exc: Optional[BaseException] = None
        self._producer_task: Optional[asyncio.Task] = None

    def _ensure_started(self) -> None:
        if not self._started:
            loop = asyncio.get_running_loop()
            self._producer_task = loop.create_task(self._producer())
            self._started = True

    async def _producer(self) -> None:
        try:
            async for item in self._source:
                self._items.append(item)
                await self._queue.put(item)
        except BaseException as e:  # propagate cancellation/errors too
            self._exc = e
        finally:
            self._done.set()
            # Signal end of stream to any active iterator.
            await self._queue.put(_SENTINEL)

    # --- async iteration support ---
    def __aiter__(self):
        self._ensure_started()
        return self

    async def __anext__(self) -> T:
        self._ensure_started()
        item = await self._queue.get()
        if item is _SENTINEL:
            if self._exc:
                raise self._exc
            raise StopAsyncIteration
        return item

    # --- awaitable support ---
    def __await__(self):
        async def _await_impl():
            self._ensure_started()
            await self._done.wait()
            if self._exc:
                raise self._exc
            return list(self._items)

        return _await_impl().__await__()

    # --- optional helpers ---
    async def to_list(self) -> list[ConsumeFromTopicEvent]:
        """Always return a list of items (collects singles into a one-item list)."""
        result = await self
        return result if isinstance(result, list) else [result]

    async def aclose(self) -> None:
        """Cancel producer task and close the underlying async generator."""
        # Cancel the producer task if it's running
        if self._producer_task is not None and not self._producer_task.done():
            self._producer_task.cancel()
            try:
                await self._producer_task
            except asyncio.CancelledError:
                # The task was cancelled by aclose(); a CancelledError here is expected.
                pass
        # Close the underlying source generator
        try:
            await self._source.aclose()
        except Exception:
            # Best-effort cleanup: ignore errors from closing the underlying source.
            pass


def async_func_wrapper(return_value) -> AsyncResult:
    """
    Normalize a function's *return value* into an AsyncResult.

    Usage:
        res: AsyncResult = async_func_wrapper(func(...))
    """
    return AsyncResult(return_value)
