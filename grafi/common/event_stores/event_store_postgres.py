from datetime import datetime
from typing import List
from typing import Optional

from loguru import logger

from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.event import Event
from grafi.common.exceptions import EventPersistenceError


try:
    from sqlalchemy import Column
    from sqlalchemy import DateTime
    from sqlalchemy import Integer
    from sqlalchemy import String
    from sqlalchemy import create_engine
    from sqlalchemy import delete
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.orm import DeclarativeBase
except ImportError:
    raise ImportError(
        "`sqlalchemy` not installed. Please install using `pip install sqlalchemy[asyncio] asyncpg`"
    )


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
    """Postgres-backed implementation of the EventStore interface with async support."""

    def __init__(
        self,
        db_url: str,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
    ):
        """
        Initialize the Postgres event store.

        Args:
            db_url: The SQLAlchemy database URL, e.g. 'postgresql://user:pass@host/dbname'.
            pool_size: The number of connections to keep in the pool (default: 5).
            max_overflow: Maximum overflow connections beyond pool_size (default: 10).
            pool_timeout: Seconds to wait for a connection from the pool (default: 30).
        """
        # Keep sync engine for initialization and sync methods
        self.engine = create_engine(
            db_url,
            echo=False,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
        )
        Base.metadata.create_all(self.engine)

        # Create async engine and session for async methods
        # Convert postgresql:// to postgresql+asyncpg://
        async_db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        if "psycopg2" in async_db_url:
            async_db_url = async_db_url.replace("psycopg2", "asyncpg")
        self.async_engine = create_async_engine(
            async_db_url,
            echo=False,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        self.AsyncSession = async_sessionmaker(
            self.async_engine, class_=AsyncSession, expire_on_commit=False
        )

    async def clear_events(self) -> None:
        """Clear all events from the database."""
        async with self.AsyncSession() as session:
            try:
                await session.execute(delete(EventModel))
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to clear events: {e}")
                raise

    async def get_events(self) -> List[Event]:
        """Get all events from the database."""
        async with self.AsyncSession() as session:
            try:
                result = await session.execute(
                    select(EventModel).order_by(EventModel.timestamp)
                )
                rows = result.scalars().all()

                events: List[Event] = []
                for r in rows:
                    event = self._create_event_from_dict(r.event_data)
                    if event:
                        events.append(event)

                return events
            except Exception as e:
                logger.error(f"Failed to get events: {e}")
                raise

    async def record_event(self, event: Event) -> None:
        """Record a single event into the database asynchronously."""
        async with self.AsyncSession() as session:
            try:
                # Convert Event object to dict
                event_dict = event.to_dict()

                # Extract conversation_id from invoke_context
                # The invoke_context is nested inside event_context
                event_context = event_dict.get("event_context", {})
                invoke_context = event_context.get("invoke_context", {})
                conversation_id = invoke_context.get("conversation_id", "")

                # Create SQLAlchemy model instance
                model = EventModel(
                    event_id=event_dict["event_id"],
                    conversation_id=conversation_id,
                    assistant_request_id=event_dict["assistant_request_id"],
                    event_type=event_dict["event_type"],
                    event_version=event_dict.get("event_version", "1.0"),
                    event_data=event_dict,
                    timestamp=datetime.fromisoformat(event_dict["timestamp"]).replace(
                        tzinfo=None
                    ),
                )
                session.add(model)
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to record event: {e}")
                raise EventPersistenceError(
                    message=f"Failed to record event: {e}",
                    cause=e,
                ) from e

    async def record_events(self, events: List[Event]) -> None:
        """Record multiple events into the database asynchronously."""
        async with self.AsyncSession() as session:
            try:
                models = []
                for event in events:
                    event_dict = event.to_dict()

                    # Extract conversation_id from invoke_context
                    event_context = event_dict.get("event_context", {})
                    invoke_context = event_context.get("invoke_context", {})
                    conversation_id = invoke_context.get("conversation_id", "")

                    models.append(
                        EventModel(
                            event_id=event_dict["event_id"],
                            conversation_id=conversation_id,
                            assistant_request_id=event_dict["assistant_request_id"],
                            event_type=event_dict["event_type"],
                            event_version=event_dict.get("event_version", "1.0"),
                            event_data=event_dict,
                            timestamp=datetime.fromisoformat(
                                event_dict["timestamp"]
                            ).replace(tzinfo=None),
                        )
                    )
                session.add_all(models)
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to record events: {e}")
                raise EventPersistenceError(
                    message=f"Failed to record events: {e}",
                    cause=e,
                ) from e

    async def get_event(self, event_id: str) -> Optional[Event]:
        """Get an event by ID asynchronously."""
        async with self.AsyncSession() as session:
            try:
                result = await session.execute(
                    select(EventModel).where(EventModel.event_id == event_id)
                )
                row = result.scalar_one_or_none()

                if not row:
                    return None

                return self._create_event_from_dict(row.event_data)
            except Exception as e:
                logger.error(f"Failed to get event {event_id}: {e}")
                raise

    async def get_agent_events(self, assistant_request_id: str) -> List[Event]:
        """Get all events for a given assistant_request_id asynchronously."""
        async with self.AsyncSession() as session:
            try:
                result = await session.execute(
                    select(EventModel)
                    .where(EventModel.assistant_request_id == assistant_request_id)
                    .order_by(EventModel.timestamp)
                )
                rows = result.scalars().all()

                if not rows:
                    return []

                events: List[Event] = []
                for r in rows:
                    event = self._create_event_from_dict(r.event_data)
                    if event:
                        events.append(event)

                return events
            except Exception as e:
                logger.error(f"Failed to get agent events {assistant_request_id}: {e}")
                raise

    async def get_conversation_events(self, conversation_id: str) -> List[Event]:
        """Get all events for a given conversation ID asynchronously."""
        async with self.AsyncSession() as session:
            try:
                result = await session.execute(
                    select(EventModel)
                    .where(EventModel.conversation_id == conversation_id)
                    .order_by(EventModel.timestamp)
                )
                rows = result.scalars().all()

                if not rows:
                    return []

                events: List[Event] = []
                for r in rows:
                    event = self._create_event_from_dict(r.event_data)
                    if event:
                        events.append(event)

                return events
            except Exception as e:
                logger.error(
                    f"Failed to get conversation events {conversation_id}: {e}"
                )
                raise

    async def get_topic_events(self, name: str, offsets: List[int]) -> List[Event]:
        """Get all events for a given topic name and specific offsets asynchronously."""
        if not offsets:
            return []

        async with self.AsyncSession() as session:
            try:
                # Use JSONB operators for efficient filtering at the database level
                # The topic name and offset are now in event_context
                stmt = (
                    select(EventModel).where(
                        # Filter by event type
                        EventModel.event_type.in_(["PublishToTopic", "TopicEvent"]),
                        # Use JSONB -> operator to navigate to event_context -> name
                        EventModel.event_data.op("->")('"event_context"').op("->>")(
                            '"name"'
                        )
                        == name,
                        # Use JSONB -> operator to navigate to event_context -> offset
                        EventModel.event_data.op("->")('"event_context"')
                        .op("->")('"offset"')
                        .astext.cast(Integer)
                        .in_(offsets),
                    )
                    # Order by offset for consistent results
                    .order_by(
                        EventModel.event_data.op("->")('"event_context"')
                        .op("->")('"offset"')
                        .astext.cast(Integer)
                    )
                )

                result = await session.execute(stmt)
                rows = result.scalars().all()

                events: List[Event] = []
                for r in rows:
                    event = self._create_event_from_dict(r.event_data)
                    if event:
                        events.append(event)

                return events
            except Exception as e:
                logger.error(f"Failed to get topic events for {name}: {e}")
                raise

    async def initialize(self) -> None:
        """Initialize the database tables asynchronously."""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
