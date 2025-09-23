from datetime import datetime
from datetime import timezone
from typing import List
from typing import Optional

from loguru import logger

from grafi.common.event_stores.event_store import EventStore
from grafi.common.events.event import Event


try:
    from sqlalchemy import JSON
    from sqlalchemy import Column
    from sqlalchemy import DateTime
    from sqlalchemy import Integer
    from sqlalchemy import String
    from sqlalchemy import create_engine
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
    Storing:
      - an auto-increment primary key,
      - the `event_id` (from your domain event),
      - the `event_type`,
      - a JSON field for the entire event data,
      - a creation timestamp.
    """

    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, unique=True, index=True, nullable=False)
    conversation_id = Column(String, index=True, nullable=False)
    assistant_request_id = Column(String, index=True, nullable=False)
    event_type = Column(String, nullable=False)
    event_context = Column(JSONB, nullable=False)
    data = Column(JSON, nullable=False)
    timestamp = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)


class EventStorePostgres(EventStore):
    """Postgres-backed implementation of the EventStore interface with async support."""

    def __init__(self, db_url: str):
        """
        Initialize the Postgres event store.
        :param db_url: The SQLAlchemy database URL, e.g. 'postgresql://user:pass@host/dbname'.
        """
        # Keep sync engine for initialization and sync methods
        self.engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self.engine)

        # Create async engine and session for async methods
        # Convert postgresql:// to postgresql+asyncpg://
        async_db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        if "psycopg2" in async_db_url:
            async_db_url = async_db_url.replace("psycopg2", "asyncpg")
        self.async_engine = create_async_engine(async_db_url, echo=False)
        self.AsyncSession = async_sessionmaker(
            self.async_engine, class_=AsyncSession, expire_on_commit=False
        )

    async def record_event(self, event: Event) -> None:
        """Record a single event into the database asynchronously."""
        async with self.AsyncSession() as session:
            try:
                # Convert Event object to dict
                event_dict = event.to_dict()

                # Create SQLAlchemy model instance
                model = EventModel(
                    event_id=event_dict["event_id"],
                    conversation_id=event_dict["event_context"]["invoke_context"][
                        "conversation_id"
                    ],
                    assistant_request_id=event_dict["assistant_request_id"],
                    event_type=event_dict["event_type"],
                    event_context=event_dict["event_context"],
                    data=event_dict["data"],
                    timestamp=event_dict["timestamp"],
                )
                session.add(model)
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to record event: {e}")
                raise e

    async def record_events(self, events: List[Event]) -> None:
        """Record multiple events into the database asynchronously."""
        async with self.AsyncSession() as session:
            try:
                models = []
                for event in events:
                    event_dict = event.to_dict()
                    models.append(
                        EventModel(
                            event_id=event_dict["event_id"],
                            conversation_id=event_dict["event_context"][
                                "invoke_context"
                            ]["conversation_id"],
                            assistant_request_id=event_dict["assistant_request_id"],
                            event_type=event_dict["event_type"],
                            event_context=event_dict["event_context"],
                            data=event_dict["data"],
                            timestamp=event_dict["timestamp"],
                        )
                    )
                session.add_all(models)
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to record events: {e}")
                raise e

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

                event_data = {
                    "event_id": row.event_id,
                    "assistant_request_id": row.assistant_request_id,
                    "event_type": row.event_type,
                    "event_context": row.event_context,
                    "data": row.data,
                    "timestamp": str(row.timestamp),
                }
                return self._create_event_from_dict(event_data)
            except Exception as e:
                logger.error(f"Failed to get event {event_id}: {e}")
                raise e

    async def get_agent_events(self, assistant_request_id: str) -> List[Event]:
        """Get all events for a given assistant_request_id asynchronously."""
        async with self.AsyncSession() as session:
            try:
                result = await session.execute(
                    select(EventModel).where(
                        EventModel.assistant_request_id == assistant_request_id
                    )
                )
                rows = result.scalars().all()

                if not rows:
                    return []

                events: List[Event] = []
                for r in rows:
                    event_data = {
                        "event_id": r.event_id,
                        "assistant_request_id": r.assistant_request_id,
                        "event_type": r.event_type,
                        "event_context": r.event_context,
                        "data": r.data,
                        "timestamp": str(r.timestamp),
                    }
                    event = self._create_event_from_dict(event_data)
                    if event:
                        events.append(event)

                return events
            except Exception as e:
                logger.error(f"Failed to get agent events {assistant_request_id}: {e}")
                raise e

    async def get_conversation_events(self, conversation_id: str) -> List[Event]:
        """Get all events for a given conversation ID asynchronously."""
        async with self.AsyncSession() as session:
            try:
                result = await session.execute(
                    select(EventModel).where(
                        EventModel.conversation_id == conversation_id
                    )
                )
                rows = result.scalars().all()

                if not rows:
                    return []

                events: List[Event] = []
                for r in rows:
                    event_data = {
                        "event_id": r.event_id,
                        "assistant_request_id": r.assistant_request_id,
                        "event_type": r.event_type,
                        "event_context": r.event_context,
                        "data": r.data,
                        "timestamp": str(r.timestamp),
                    }
                    event = self._create_event_from_dict(event_data)
                    if event:
                        events.append(event)

                return events
            except Exception as e:
                logger.error(
                    f"Failed to get conversation events {conversation_id}: {e}"
                )
                raise e

    async def get_topic_events(self, name: str, offsets: List[int]) -> List[Event]:
        """Get all events for a given topic name and specific offsets asynchronously."""
        if not offsets:
            return []

        async with self.AsyncSession() as session:
            try:
                # Use JSONB operators for efficient filtering at the database level
                stmt = (
                    select(EventModel).where(
                        # Filter by event type
                        EventModel.event_type.in_(["PublishToTopic", "OutputTopic"]),
                        # Use JSONB ->> operator to extract name and compare
                        EventModel.event_context.op("->>")("name") == name,
                        # Use JSONB -> operator to extract offset and check if it's in our list
                        EventModel.event_context.op("->")("offset")
                        .astext.cast(Integer)
                        .in_(offsets),
                    )
                    # Order by offset for consistent results
                    .order_by(
                        EventModel.event_context.op("->")("offset").astext.cast(Integer)
                    )
                )

                result = await session.execute(stmt)
                rows = result.scalars().all()

                events: List[Event] = []
                for r in rows:
                    event_data = {
                        "event_id": r.event_id,
                        "assistant_request_id": r.assistant_request_id,
                        "event_type": r.event_type,
                        "event_context": r.event_context,
                        "data": r.data,
                        "timestamp": str(r.timestamp),
                    }
                    event = self._create_event_from_dict(event_data)
                    if event:
                        events.append(event)

                return events
            except Exception as e:
                logger.error(f"Failed to get topic events for {name}: {e}")
                raise e

    async def initialize(self) -> None:
        """Initialize the database tables asynchronously."""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
