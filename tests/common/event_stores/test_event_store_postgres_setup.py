"""EventStorePostgres connects lazily: constructing it does no I/O, and its first
use creates the events table, under a lock any concurrent creator waits for."""

import asyncio
from typing import Any

import pytest

from grafi.common.event_stores.event_store_postgres import EventStorePostgres
from grafi.common.exceptions import EventPersistenceError

# Nothing listens on port 1.
UNREACHABLE = "postgresql://user:password@127.0.0.1:1/grafi"


class _Engine:
    """Records the statements run while preparing the table."""

    def __init__(self) -> None:
        self.statements: list = []
        self.tables_created = 0
        self.disposed = False

    def begin(self) -> "_Engine":
        return self

    async def __aenter__(self) -> "_Engine":
        await asyncio.sleep(0)  # Lets concurrent first uses interleave.
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def execute(self, statement: Any, params: Any) -> None:
        self.statements.append(str(statement))

    async def run_sync(self, create_all: Any) -> None:
        self.tables_created += 1

    async def dispose(self) -> None:
        self.disposed = True


class _Session:
    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def execute(self, statement: Any) -> None:
        return None

    async def commit(self) -> None:
        return None


def test_constructing_the_store_does_no_io() -> None:
    EventStorePostgres(UNREACHABLE)


@pytest.mark.asyncio
async def test_the_first_use_creates_the_table_under_a_lock() -> None:
    store = EventStorePostgres(UNREACHABLE)
    engine = _Engine()
    store.async_engine = engine  # type: ignore[assignment]
    store.AsyncSession = _Session  # type: ignore[assignment]

    await store.clear_events()
    await asyncio.gather(store.clear_events(), store.clear_events())

    assert engine.tables_created == 1
    assert engine.statements == ["SELECT pg_advisory_xact_lock(:key)"]


@pytest.mark.asyncio
async def test_concurrent_first_uses_create_the_table_once() -> None:
    # One creates it; the others wait without holding a pooled connection.
    store = EventStorePostgres(UNREACHABLE)
    engine = _Engine()
    store.async_engine = engine  # type: ignore[assignment]
    store.AsyncSession = _Session  # type: ignore[assignment]

    await asyncio.gather(*(store.clear_events() for _ in range(5)))

    assert engine.tables_created == 1


class _DownEngine(_Engine):
    """A database that fails every connection, slowly."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    async def __aenter__(self) -> "_Engine":
        self.attempts += 1
        await asyncio.sleep(0.01)
        raise OSError("connection refused")


@pytest.mark.asyncio
async def test_concurrent_first_uses_share_one_failed_attempt() -> None:
    # During an outage, waiters get the one attempt's error, not one each.
    store = EventStorePostgres(UNREACHABLE)
    engine = _DownEngine()
    store.async_engine = engine  # type: ignore[assignment]

    results = await asyncio.gather(
        *(store.clear_events() for _ in range(5)), return_exceptions=True
    )

    assert engine.attempts == 1
    assert all(isinstance(result, EventPersistenceError) for result in results)
    # Each caller's own error, so its handling (ids, notes) is its own.
    assert len({id(result) for result in results}) == 5
    assert len({id(result.__cause__) for result in results}) == 1
    with pytest.raises(EventPersistenceError):  # The next use tries again.
        await store.clear_events()
    assert engine.attempts == 2


@pytest.mark.asyncio
async def test_aclose_closes_the_connection_pool() -> None:
    store = EventStorePostgres(UNREACHABLE)
    engine = _Engine()
    store.async_engine = engine  # type: ignore[assignment]
    await store.aclose()
    assert engine.disposed


@pytest.mark.asyncio
async def test_aclose_can_be_called_again() -> None:
    store = EventStorePostgres(UNREACHABLE)
    await store.aclose()
    await store.aclose()


@pytest.mark.asyncio
async def test_an_unreachable_database_fails_on_first_use() -> None:
    store = EventStorePostgres(UNREACHABLE)
    with pytest.raises(EventPersistenceError) as raised:
        await store.clear_events()
    assert raised.value.operation == "initialize"
    assert isinstance(raised.value.__cause__, OSError)  # Connection refused.
    await store.async_engine.dispose()
