"""Closing helpers for async iterators and resources.

Every layer that forwards an async iterator closes it before returning
(``owned_iterator``). A failure while closing never replaces the error or the
cancellation already propagating: it is kept as a note on it, or logged with
its traceback when nothing can carry it.

The context managers here are classes rather than ``@asynccontextmanager``
generators: a loop shutting down closes every open async generator at once,
and would close such a helper in the middle of its own exit.

A workflow run keeps foreign code (tools, stores) out of the caller's task by
running it in tasks of its own; see
:mod:`grafi.workflows.impl.workflow_run`. ``isolated`` does the same for a
single call made on the caller's behalf.
"""

import asyncio
import functools
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any
from typing import AsyncIterator
from typing import Awaitable
from typing import Callable
from typing import Generic
from typing import Iterable
from typing import Optional
from typing import Type
from typing import TypeVar

from loguru import logger

T = TypeVar("T")

# The label of a failure kept as a note on the error that is raised instead.
_SECONDARY_FAILURE = "Secondary cleanup failure"

# Interrupts and exits. asyncio raises one out of the loop from the task that
# raised it; raised again from another task, it would leave the loop twice and
# cut short the cleanup of whatever runs the loop (``asyncio.run()``). Other
# tasks get an ordinary error caused by it instead.
INTERRUPT_OR_EXIT = (KeyboardInterrupt, SystemExit)


def error_rank(error: BaseException) -> int:
    """How an error ranks when several end one operation: an interrupt or exit
    (2) outranks a cancellation (1), which outranks a failure (0)."""
    if isinstance(error, Exception):
        return 0
    return 1 if isinstance(error, asyncio.CancelledError) else 2


def unexpected_cancellation(
    message: str, cause: Optional[BaseException] = None
) -> RuntimeError:
    """The failure reported for a cancellation nobody requested, chained to it."""
    failure = RuntimeError(message)
    failure.__cause__ = cause
    return failure


def cancellation_of(task: "asyncio.Task[Any]") -> asyncio.CancelledError:
    """The CancelledError a cancelled task ended with, keeping its message."""
    try:
        task.result()
    except asyncio.CancelledError as cancelled:
        return cancelled
    raise ValueError(f"{task!r} was not cancelled")


async def wait_all(futures: Iterable["asyncio.Future[Any]"]) -> bool:
    """Wait until ``futures`` have all ended, however often the caller is
    cancelled meanwhile, as they must not be abandoned; and return whether it
    was. The cancellation is not raised: the caller raises it, or its own
    error, which a cancellation outranks."""
    futures, cancelled = list(futures), False
    while pending := [future for future in futures if not future.done()]:
        try:
            await asyncio.wait(pending)
        except asyncio.CancelledError:
            cancelled = True  # Still waited for.
    return cancelled


async def isolated(call: Callable[[], Awaitable[T]], description: str) -> T:
    """Await ``call()`` in a task of its own, so the caller's cancellation
    stays the caller's. The task first yields to the loop, so ``call`` never
    runs in the caller's frame under an eager task factory (Python 3.12+).

    If the caller is cancelled meanwhile, the cancellation is forwarded, the
    task is waited for (never abandoned), and the caller's own CancelledError is
    raised with the task's failure noted on it; another ``BaseException`` the
    task ends with is raised instead. A task that ends cancelled on its own has
    failed, and one that ends with an interrupt or exit (which left the loop
    through it: see ``INTERRUPT_OR_EXIT``) has failed because of it; either way
    the caller gets a ``RuntimeError`` naming the ``description``.
    """

    async def started() -> T:
        await asyncio.sleep(0)
        return await call()

    task = asyncio.create_task(started())
    try:
        await asyncio.wait({task})  # Raises only the caller's cancellation.
    except asyncio.CancelledError as cancellation:
        while not task.done():
            task.cancel()
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:
                pass  # Forwarded again; still waited for.
        error = None if task.cancelled() else task.exception()
        if isinstance(error, (Exception, *INTERRUPT_OR_EXIT)):
            note_failure(cancellation, error, _SECONDARY_FAILURE)
        elif error is not None:
            raise error  # Another BaseException outranks the cancellation.
        raise
    if task.cancelled():
        raise unexpected_cancellation(
            f"{description} was unexpectedly cancelled", cancellation_of(task)
        )
    error = task.exception()
    if isinstance(error, INTERRUPT_OR_EXIT):
        raise RuntimeError(f"{description} was interrupted") from error
    return task.result()


def note_failure(target: BaseException, error: BaseException, label: str) -> None:
    """Keep ``error`` visible as a note on ``target``, the error being raised."""
    note = f"{label}: {type(error).__name__}: {error}"
    target.add_note(note)
    logger.opt(exception=error).warning("{}", note)  # The note has no traceback.


def log_not_raised(error: BaseException, reason: str) -> None:
    """Log a failure that is kept out of the way, with its traceback, as it is
    raised nowhere else."""
    logger.opt(exception=error).warning(
        "Not raised, as {}: {}: {}", reason, type(error).__name__, error
    )


def cancelling() -> bool:
    """Whether the current task has a cancellation pending, by asyncio's count
    (which, as for ``asyncio.timeout``, relies on code that swallows a
    cancellation calling ``uncancel()``)."""
    try:
        task = asyncio.current_task()
    except RuntimeError:
        return False  # No loop: a generator finalized after its loop closed.
    return task is not None and task.cancelling() > 0


def note_on_primary(
    primary: Optional[BaseException],
    error: BaseException,
    label: str = _SECONDARY_FAILURE,
) -> bool:
    """Note a cleanup ``error`` on the ``primary`` exception if that must win.

    Returns True when ``error`` was noted, so the caller lets ``primary`` go
    on; False when the caller should raise ``error`` instead. ``primary`` wins
    over an ``Exception``, except a plain close (``GeneratorExit`` without a
    cancellation in progress), which a close failure replaces as it would for
    a generator. An interrupt or exit also wins over a cancellation, so that
    one already leaving the loop is not lost. Otherwise a cancellation,
    interrupt or exit raised in cleanup is never noted.
    """
    if isinstance(primary, INTERRUPT_OR_EXIT) and isinstance(
        error, asyncio.CancelledError
    ):
        note_failure(primary, error, label)
        return True
    if (
        not isinstance(error, Exception)  # Cancellation, KeyboardInterrupt, exit.
        or primary is None
        or (isinstance(primary, GeneratorExit) and not cancelling())
    ):
        return False
    note_failure(primary, error, label)
    return True


async def _clean_up(
    primary: Optional[BaseException], cleanup: Callable[[], Awaitable[object]]
) -> None:
    """Await ``cleanup`` as a block exits with ``primary`` (None when it did
    not fail); a failure to clean up never replaces ``primary``, see
    note_on_primary()."""
    try:
        await cleanup()
    except BaseException as error:
        if not note_on_primary(primary, error):
            raise


class _OnExit(Generic[T]):
    """Provides ``value`` to an ``async with`` block and awaits ``cleanup`` as
    the block exits, preserving the primary failure. With ``best_effort`` (a
    label for the log), a failure to clean up is logged as by
    :func:`best_effort_close` rather than raised."""

    def __init__(
        self,
        value: T,
        cleanup: Callable[[], Awaitable[object]],
        best_effort: Optional[str] = None,
    ) -> None:
        self._value = value
        if best_effort is not None:
            cleanup = functools.partial(best_effort_close, cleanup, best_effort)
        self._cleanup = cleanup

    async def __aenter__(self) -> T:
        return self._value

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        primary: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        await _clean_up(primary, self._cleanup)


def cleanup_on_exit(
    cleanup: Callable[[], Awaitable[object]], *, best_effort: Optional[str] = None
) -> AbstractAsyncContextManager[None]:
    """Await ``cleanup`` when the block exits, preserving the primary failure;
    ``best_effort`` as for :func:`owned_iterator`."""
    return _OnExit(None, cleanup, best_effort)


async def close_iterator(source: object) -> None:
    """Close ``source`` if it can be closed.

    A generator already running is left alone: another task is closing it (as
    when the loop shuts down and closes every open generator at once), and
    that close finishes it.
    """
    close = getattr(source, "aclose", None)
    if close is not None and not getattr(source, "ag_running", False):
        await close()


async def best_effort_close(close: Callable[[], Awaitable[object]], label: str) -> None:
    """Close a resource, logging rather than raising a failure to close it.

    For resources released after a completed call: failing to release them must
    not fail a call whose output was already delivered.
    """
    try:
        await close()
    except Exception as error:
        logger.opt(exception=error).warning("{} close failed: {!r}", label, error)


class _BestEffortExit(Generic[T]):
    def __init__(self, manager: AbstractAsyncContextManager[T], label: str) -> None:
        self._manager = manager
        self._label = label

    async def __aenter__(self) -> T:
        return await self._manager.__aenter__()

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        error: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        def release() -> Awaitable[object]:
            return self._manager.__aexit__(exc_type, error, traceback)

        await _clean_up(
            error, functools.partial(best_effort_close, release, self._label)
        )


def best_effort_exit(
    manager: AbstractAsyncContextManager[T], label: str
) -> AbstractAsyncContextManager[T]:
    """Use an async context manager whose exit only releases a resource.

    The exit sees the body's exception as with ``async with``, but cannot
    suppress it, and a failure to exit is logged rather than raised, so
    releasing a client cannot fail a call that already completed.
    """
    return _BestEffortExit(manager, label)


def owned_iterator(
    source: AsyncIterator[T], *, best_effort: Optional[str] = None
) -> AbstractAsyncContextManager[AsyncIterator[T]]:
    """Close ``source`` (see :func:`close_iterator`) before its owner returns.

    With ``best_effort`` (a label for the log), closing only releases a
    resource, so a failure to close is logged as by :func:`best_effort_close`.
    """
    return _OnExit(source, functools.partial(close_iterator, source), best_effort)
