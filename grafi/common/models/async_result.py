import asyncio
import inspect
from typing import Any
from typing import Generic
from typing import Optional
from typing import TypeVar


_SENTINEL = object()


T = TypeVar("T")


class AsyncResult(Generic[T]):
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

    def __init__(self, source: Any):
        self._source = source
        self._kind = (
            "agen"
            if inspect.isasyncgen(source)
            else "awaitable" if inspect.isawaitable(source) else "value"
        )

        self._queue: asyncio.Queue[T] = asyncio.Queue()
        self._items: list[T] = []
        self._done = asyncio.Event()
        self._started = False
        self._exc: Optional[BaseException] = None

    def _ensure_started(self) -> None:
        if not self._started:
            loop = asyncio.get_running_loop()
            loop.create_task(self._producer())
            self._started = True

    async def _producer(self) -> None:
        try:
            if self._kind == "agen":
                async for item in self._source:
                    self._items.append(item)
                    await self._queue.put(item)
            elif self._kind == "awaitable":
                val = await self._source
                self._items.append(val)
                await self._queue.put(val)
            else:  # "value"
                self._items.append(self._source)
                await self._queue.put(self._source)
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
            if self._kind == "agen":
                # Awaiting a stream returns all collected items.
                return list(self._items)
            # Awaiting a single result returns that result.
            return self._items[0] if self._items else None

        return _await_impl().__await__()

    # --- optional helpers ---
    async def to_list(self) -> list[T]:
        """Always return a list of items (collects singles into a one-item list)."""
        result = await self
        return result if isinstance(result, list) else [result]

    async def aclose(self) -> None:
        """Attempt to close the underlying async generator (if any)."""
        if self._kind == "agen":
            try:
                await self._source.aclose()
            except Exception:
                pass
