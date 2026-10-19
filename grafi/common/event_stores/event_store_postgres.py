import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
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
    from sqlalchemy import delete
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
    event_version = Column(String, nullable=False, default="1.0")
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

    def _row_to_event(self, row: "EventModel") -> Optional[Event]:
        """Decode a single ``EventModel`` row into an :class:`Event`.

        Centralizes the row-to-event conversion shared by every query method.
        ``row.event_data`` is a JSONB column typed as ``Column[Any]`` at the
        class level; at the instance level it holds the stored dict.
        """
        return self._create_event_from_dict(cast(Dict[str, Any], row.event_data))

    async def get_events(self) -> List[Event]:
        """Get all events from the database."""
        async with self._session() as session:
            try:
                result = await session.execute(
                    select(EventModel).order_by(EventModel.timestamp, EventModel.id)
                )
                rows = result.scalars().all()

                events: List[Event] = []
                for r in rows:
                    event = self._row_to_event(r)
                    if event:
                        events.append(event)

                return events
            except Exception as e:
                raise self._persistence_error(
                    "Failed to read events", "get_events", e
                ) from e

    @staticmethod
    def _event_values(event: Event) -> dict:
        """Flatten an :class:`Event` into a column-value dict for insertion."""
        event_dict = event.to_dict()
        # The invoke_context is nested inside event_context.
        event_context = event_dict.get("event_context", {})
        invoke_context = event_context.get("invoke_context", {})
        conversation_id = invoke_context.get("conversation_id", "")
        return {
            "event_id": event_dict["event_id"],
            "conversation_id": conversation_id,
            "assistant_request_id": event_dict["assistant_request_id"],
            "event_type": event_dict["event_type"],
            "event_version": event_dict.get("event_version", "1.0"),
            "event_data": event_dict,
            "timestamp": datetime.fromisoformat(event_dict["timestamp"]).replace(
                tzinfo=None
            ),
        }

    async def record_event(self, event: Event) -> None:
        """Record a single event idempotently (no-op on duplicate event_id)."""
        async with self._session() as session:
            try:
                stmt = (
                    pg_insert(EventModel)
                    .values(**self._event_values(event))
                    .on_conflict_do_nothing(index_elements=["event_id"])
                )
                await session.execute(stmt)
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise self._persistence_error(
                    "Failed to record event", "record_event", e
                ) from e

    async def record_events(self, events: Sequence[Event]) -> None:
        """Record multiple events idempotently.

        Duplicate ``event_id`` rows are skipped via ``ON CONFLICT DO NOTHING``
        rather than aborting the whole batch, so replay/retry stays idempotent.
        """
        if not events:
            return
        async with self._session() as session:
            try:
                # One statement, compiled once and executed for every row in
                # one transaction, so a batch of any size is written atomically.
                await session.execute(
                    pg_insert(EventModel).on_conflict_do_nothing(
                        index_elements=["event_id"]
                    ),
                    [self._event_values(event) for event in events],
                )
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise self._persistence_error(
                    "Failed to record events", "record_events", e
                ) from e

    async def get_event(self, event_id: str) -> Optional[Event]:
        """Get an event by ID asynchronously."""
        async with self._session() as session:
            try:
                result = await session.execute(
                    select(EventModel).where(EventModel.event_id == event_id)
                )
                row = result.scalar_one_or_none()

                if not row:
                    return None

                return self._row_to_event(row)
            except Exception as e:
                raise self._persistence_error(
                    "Failed to read event", f"get_event:{event_id}", e
                ) from e

    async def get_agent_events(self, assistant_request_id: str) -> List[Event]:
        """Get all events for a given assistant_request_id asynchronously."""
        async with self._session() as session:
            try:
                result = await session.execute(
                    select(EventModel)
                    .where(EventModel.assistant_request_id == assistant_request_id)
                    .order_by(EventModel.timestamp, EventModel.id)
                )
                rows = result.scalars().all()

                if not rows:
                    return []

                events: List[Event] = []
                for r in rows:
                    event = self._row_to_event(r)
                    if event:
                        events.append(event)

                return events
            except Exception as e:
                raise self._persistence_error(
                    "Failed to read agent events",
                    f"get_agent_events:{assistant_request_id}",
                    e,
                ) from e

    async def get_conversation_events(self, conversation_id: str) -> List[Event]:
        """Get all events for a given conversation ID asynchronously."""
        async with self._session() as session:
            try:
                result = await session.execute(
                    select(EventModel)
                    .where(EventModel.conversation_id == conversation_id)
                    .order_by(EventModel.timestamp, EventModel.id)
                )
                rows = result.scalars().all()

                if not rows:
                    return []

                events: List[Event] = []
                for r in rows:
                    event = self._row_to_event(r)
                    if event:
                        events.append(event)

                return events
            except Exception as e:
                raise self._persistence_error(
                    "Failed to read conversation events",
                    f"get_conversation_events:{conversation_id}",
                    e,
                ) from e

    async def get_topic_events(self, name: str, offsets: List[int]) -> List[Event]:
        """Get all events for a given topic name and specific offsets asynchronously."""
        if not offsets:
            return []

        async with self._session() as session:
            try:
                # Use JSONB operators for efficient filtering at the database level
                # The topic name and offset are now in event_context
                stmt = (
                    select(EventModel).where(
                        # Filter by event type
                        EventModel.event_type.in_(["PublishToTopic", "TopicEvent"]),
                        # JSONB navigation: event_data -> 'event_context' ->> 'name'.
                        # Keys are passed unquoted; quoting them ('"name"') makes the
                        # operator look up a key that literally includes quotes and
                        # therefore matches nothing.
                        EventModel.event_data.op("->")("event_context").op("->>")(
                            "name"
                        )
                        == name,
                        # event_data -> 'event_context' -> 'offset' (cast to int)
                        EventModel.event_data.op("->")("event_context")
                        .op("->")("offset")
                        .astext.cast(Integer)
                        .in_(offsets),
                    )
                    # Order by offset for consistent results
                    .order_by(
                        EventModel.event_data.op("->")("event_context")
                        .op("->")("offset")
                        .astext.cast(Integer)
                    )
                )

                result = await session.execute(stmt)
                rows = result.scalars().all()

                events: List[Event] = []
                for r in rows:
                    event = self._row_to_event(r)
                    if event:
                        events.append(event)

                return events
            except Exception as e:
                raise self._persistence_error(
                    "Failed to read topic events", f"get_topic_events:{name}", e
                ) from e
