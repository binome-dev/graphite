from collections import deque
from typing import Any
from typing import AsyncGenerator
from typing import Deque
from typing import Generator
from typing import NoReturn
from typing import Optional

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)


class _CapturedFailure:
    """A failure kept to be raised again.

    Each raise starts from the original traceback and context, so repeated
    raises neither keep growing the traceback nor keep the context of an
    earlier raise.
    """

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self._traceback = error.__traceback__
        self._context = error.__context__

    def raise_again(self) -> NoReturn:
        self.error.__context__ = self._context
        raise self.error.with_traceback(self._traceback)


class AsyncResult:
    """An async iterator of output events that can also be awaited.

    - ``async for event in result`` reads the events as the source yields them.
    - ``await result`` returns a list of the events not yet read.

    The source runs in the reader's task and nothing is read ahead, so
    cancelling a read closes the source. Read from one task at a time, and
    bound a read with ``asyncio.timeout()``, not ``asyncio.wait_for()`` (on
    Python 3.11 it runs the read in another task, which a second cancellation
    abandons even while it closes the source).

    A stream that did not finish never looks complete: after a failure or a
    cancelled read every later read raises, and ``await`` raises for a source
    closed early by ``aclose()`` (iteration then just ends, as for a
    generator). Events an ``await`` collected before it failed or was
    cancelled stay readable with ``async for`` first, as the source counted
    them as delivered.
    """

    def __init__(self, source: AsyncGenerator[ConsumeFromTopicEvent, None]) -> None:
        self._source = source
        self._received: Deque[ConsumeFromTopicEvent] = deque()
        self._failure: Optional[_CapturedFailure] = None
        self._ended = False  # The source ended by itself.
        self._closed = False  # aclose() was called.

    def __aiter__(self) -> "AsyncResult":
        return self

    async def __anext__(self) -> ConsumeFromTopicEvent:
        if self._received:
            return self._received.popleft()
        return await self._read()

    async def _read(self) -> ConsumeFromTopicEvent:
        if self._failure is None:
            try:
                return await anext(self._source)
            except StopAsyncIteration:
                if not self._closed:
                    self._ended = True
                raise
            except Exception as error:
                self._failure = _CapturedFailure(error)
            except BaseException:
                # The cancelled read closed the source.
                self._failure = _CapturedFailure(_closed_early())
                raise
        self._failure.raise_again()  # Every read raises it the same way.

    def __await__(self) -> Generator[Any, None, list[ConsumeFromTopicEvent]]:
        return self._collect().__await__()

    async def _collect(self) -> list[ConsumeFromTopicEvent]:
        while True:
            try:
                self._received.append(await self._read())
            except StopAsyncIteration:
                break
        if not self._ended:
            raise _closed_early()
        items = list(self._received)
        self._received.clear()
        return items

    async def to_list(self) -> list[ConsumeFromTopicEvent]:
        """Return the events not yet read."""
        return await self

    async def aclose(self) -> None:
        """Close the source, as ``aclose()`` closes a generator."""
        self._closed = True
        await self._source.aclose()


def _closed_early() -> RuntimeError:
    return RuntimeError("AsyncResult was closed before its stream finished")


def async_func_wrapper(
    return_value: AsyncGenerator[ConsumeFromTopicEvent, None],
) -> AsyncResult:
    """
    Normalize a function's *return value* into an AsyncResult.

    Usage:
        res: AsyncResult = async_func_wrapper(func(...))
    """
    return AsyncResult(return_value)
