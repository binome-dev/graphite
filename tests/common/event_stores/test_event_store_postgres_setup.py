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

    def begin(self) -> "_Engine":
        return self

    async def __aenter__(self) -> "_Engine":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def execute(self, statement: Any, params: Any) -> None:
        self.statements.append(str(statement))

    async def run_sync(self, create_all: Any) -> None:
        self.tables_created += 1


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
async def test_an_unreachable_database_fails_on_first_use() -> None:
    store = EventStorePostgres(UNREACHABLE)
    with pytest.raises(EventPersistenceError) as raised:
        await store.clear_events()
    assert raised.value.operation == "initialize"
    assert isinstance(raised.value.__cause__, OSError)  # Connection refused.
    await store.async_engine.dispose()
