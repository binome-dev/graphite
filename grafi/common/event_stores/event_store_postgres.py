import asyncio
from contextlib import asynccontextmanager
from datetime import timezone
from typing import Any
from typing import AsyncIterator
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import cast

from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.event import Event
from grafi.common.exceptions import EventPersistenceError

try:
    import asyncpg  # noqa: F401 - the driver the engine loads.
    from sqlalchemy import Column
    from sqlalchemy import DateTime
    from sqlalchemy import Integer
    from sqlalchemy import String
    from sqlalchemy import cast as cast_
    from sqlalchemy import delete
    from sqlalchemy import func
    from sqlalchemy import select
    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.orm import DeclarativeBase
except ImportError:
    raise ImportError("EventStorePostgres needs: pip install 'grafi[postgres]'")


# The key of the advisory lock taken while creating the events table.
_TABLE_LOCK = 0x67726166690001


class Base(DeclarativeBase):
    pass


class EventModel(Base):
    """
    SQLAlchemy model representing an event record.
    Stores event data with proper indexing for efficient queries.

    Note: Timestamps are stored as timezone-naive UTC datetimes.
    Event timestamps are created as timezone-aware (UTC) but converted
    to naive for storage to avoid timezone comparison issues.
    """

    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, unique=True, index=True, nullable=False)
    conversation_id = Column(String, index=True, nullable=False)
    assistant_request_id = Column(String, index=True, nullable=False)
    event_type = Column(String, index=True, nullable=False)
    event_version = Column(String, nullable=False)
    event_data = Column(JSONB, nullable=False)
    timestamp = Column(DateTime, nullable=False)  # Stored as naive UTC


class EventStorePostgres(EventStore):
    """An EventStore in Postgres, through asyncpg. It connects lazily, and creates
    its table on first use."""

    def __init__(
        self,
        db_url: str,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
    ):
        """
        Args:
            db_url: The database URL, e.g. 'postgresql://user:pass@host/dbname'.
            pool_size: The number of connections to keep in the pool (default: 5).
            max_overflow: Maximum overflow connections beyond pool_size (default: 10).
            pool_timeout: Seconds to wait for a connection from the pool (default: 30).
        """
        self.async_engine = create_async_engine(
            make_url(db_url).set(drivername="postgresql+asyncpg"),
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
        )
        self.AsyncSession = async_sessionmaker(
            self.async_engine, class_=AsyncSession, expire_on_commit=False
        )
        self._table_ready = False
        self._table_creation: Optional[asyncio.Task[None]] = None

    async def initialize(self) -> None:
        """Create the events table unless it exists. The first use does so; call
        it at startup to fail fast if the database is unreachable.

        Concurrent callers share one attempt, and its outcome, holding no
        pooled connection while they wait; the next call retries a failed one.
        An attempt belongs to its event loop.
        """
        loop = asyncio.get_running_loop()
        creation = self._table_creation
        if (
            creation is None
            or creation.get_loop() is not loop
            or (creation.done() and (creation.cancelled() or creation.exception()))
        ):
            creation = self._table_creation = loop.create_task(self._create_table())
            # Its error is retrieved even if every caller was cancelled.
            creation.add_done_callback(
                lambda task: task.cancelled() or task.exception()
            )
        try:
            # Shielded: a caller cancelled does not cancel the others' attempt.
            await asyncio.shield(creation)
        except Exception as e:  # Each caller's own error, of the shared cause.
            raise self._persistence_error(
                "Failed to reach the database or create the events table",
                "initialize",
                e,
            ) from e

    async def _create_table(self) -> None:
        async with self.async_engine.begin() as connection:
            # Serializes table creation across processes.
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _TABLE_LOCK}
            )
            await connection.run_sync(Base.metadata.create_all)
        self._table_ready = True

    async def aclose(self) -> None:
        """Close the connection pool."""
        await self.async_engine.dispose()

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        """A session on the events table, created first if need be."""
        if not self._table_ready:
            await self.initialize()
        async with self.AsyncSession() as session:
            yield session

    @staticmethod
    def _persistence_error(
        message: str, operation: str, cause: Exception
    ) -> EventPersistenceError:
        """Build an :class:`EventPersistenceError` with stable message and the
        operation (including any relevant identifier) as structured context.

        Centralizes translation so every store method surfaces a consistent
        domain error instead of a raw backend exception, and so the original
        cause is always preserved (the lifecycle decorator emits the record)."""
        err = EventPersistenceError(message=message, cause=cause)
        # Captured by serialization's _DOMAIN_FIELDS for a precise diagnostic.
        err.operation = operation  # type: ignore[attr-defined]
        return err

    async def clear_events(self) -> None:
        """Clear all events from the database."""
        async with self._session() as session:
            try:
                await session.execute(delete(EventModel))
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise self._persistence_error(
                    "Failed to clear events", "clear_events", e
                ) from e

    async def _select(self, statement: Any, operation: str) -> List[Event]:
        """The events of the rows ``statement`` selects, in its order.

        Raises:
            EventPersistenceError: If the query fails.
            EventSerializationError: If a row cannot be decoded (see
                :class:`~grafi.common.events.event_codec.EventCodec`).
        """
        async with self._session() as session:
            try:
                result = await session.execute(statement)
                rows = result.scalars().all()
            except Exception as e:
                raise self._persistence_error(
                    "Failed to read events", operation, e
                ) from e
        return [
            self.codec.decode(cast(Dict[str, Any], row.event_data)) for row in rows
        ]

    async def get_events(self) -> List[Event]:
        """Get all events from the database."""
        return await self._select(
            select(EventModel).order_by(EventModel.timestamp, EventModel.id),
            "get_events",
        )

    def _event_values(self, event: Event) -> Dict[str, Any]:
        """An :class:`Event` as the column values of its row, taken from its
        stored JSON, so an event type of your own is stored too."""
        data = self.codec.encode(event)
        timestamp = event.timestamp  # Stored naive, in UTC; naive is UTC.
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
        return {
            "event_id": data["event_id"],
            "conversation_id": event.invoke_context.conversation_id,
            "assistant_request_id": event.invoke_context.assistant_request_id,
            "event_type": data["event_type"],
            "event_version": str(data["event_version"]),
            "event_data": data,
            "timestamp": timestamp,
        }

    async def record_event(self, event: Event) -> None:
        """Record a single event idempotently (no-op on duplicate event_id)."""
        await self.record_events([event])

    async def record_events(self, events: Sequence[Event]) -> None:
        """Record multiple events idempotently.

        Duplicate ``event_id`` rows are skipped via ``ON CONFLICT DO NOTHING``
        rather than aborting the whole batch, so replay/retry stays idempotent.

        Raises:
            EventSerializationError: If an event cannot be encoded; nothing is
                written.
            EventPersistenceError: If writing fails; nothing is written.
        """
        if not events:
            return
        rows = [self._event_values(event) for event in events]
        async with self._session() as session:
            try:
                # One statement, compiled once and executed for every row in
                # one transaction, so a batch of any size is written atomically.
                await session.execute(
                    pg_insert(EventModel).on_conflict_do_nothing(
                        index_elements=["event_id"]
                    ),
                    rows,
                )
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise self._persistence_error(
                    "Failed to record events", "record_events", e
                ) from e

    async def get_event(self, event_id: str) -> Optional[Event]:
        """Get an event by ID asynchronously."""
        events = await self._select(
            select(EventModel).where(EventModel.event_id == event_id),
            f"get_event:{event_id}",
        )
        return events[0] if events else None

    async def get_agent_events(self, assistant_request_id: str) -> List[Event]:
        """Get all events for a given assistant_request_id asynchronously."""
        return await self._select(
            select(EventModel)
            .where(EventModel.assistant_request_id == assistant_request_id)
            .order_by(EventModel.timestamp, EventModel.id),
            f"get_agent_events:{assistant_request_id}",
        )

    async def get_conversation_events(self, conversation_id: str) -> List[Event]:
        """Get all events for a given conversation ID asynchronously."""
        return await self._select(
            select(EventModel)
            .where(EventModel.conversation_id == conversation_id)
            .order_by(EventModel.timestamp, EventModel.id),
            f"get_conversation_events:{conversation_id}",
        )

    async def get_topic_events(self, name: str, offsets: List[int]) -> List[Event]:
        """Get the publications to the topic ``name`` at ``offsets``, by offset."""
        if not offsets:
            return []
        offset = cast_(_topic_field("offset"), Integer)
        return await self._select(
            select(EventModel)
            .where(
                EventModel.event_type.in_(["PublishToTopic", "TopicEvent"]),
                _topic_field("name") == name,
                offset.in_(offsets),
            )
            .order_by(offset),
            f"get_topic_events:{name}",
        )


def _topic_field(key: str) -> Any:
    """A topic event's field ``key`` in its stored JSON, of either version:
    under ``event_context`` (version 1), or at the top level (version 2).
    Keys are passed unquoted; quoting them ('"name"') makes the operator look
    up a key that literally includes quotes, which matches nothing."""
    version_1 = EventModel.event_data.op("->")("event_context").op("->>")(key)
    return func.coalesce(version_1, EventModel.event_data.op("->>")(key))
