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
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.orm import DeclarativeBase
    from sqlalchemy.orm import sessionmaker
except ImportError:
    raise ImportError(
        "`sqlalchemy` not installed. Please install using `pip install sqlalchemy`"
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
    """Postgres-backed implementation of the EventStore interface."""

    def __init__(self, db_url: str):
        """
        Initialize the Postgres event store.
        :param db_url: The SQLAlchemy database URL, e.g. 'postgresql://user:pass@host/dbname'.
        """
        self.engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def record_event(self, event: Event) -> None:
        """Record a single event into the database."""
        session = self.Session()
        try:
            # Convert Event object to dict (assuming your Event class has a .to_dict() method)
            event_dict = event.to_dict()

            # Create SQLAlchemy model instance
            model = EventModel(
                event_id=event_dict["event_id"],
                conversation_id=event_dict["event_context"]["execution_context"][
                    "conversation_id"
                ],
                assistant_request_id=event_dict["assistant_request_id"],
                event_type=event_dict["event_type"],
                event_context=event_dict["event_context"],
                data=event_dict["data"],
                timestamp=event_dict["timestamp"],
            )
            session.add(model)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to record event: {e}")
            raise e
        finally:
            session.close()

    def record_events(self, events: List[Event]) -> None:
        """Record multiple events into the database."""
        session = self.Session()
        try:
            models = []
            for event in events:
                event_dict = event.to_dict()
                models.append(
                    EventModel(
                        event_id=event_dict["event_id"],
                        conversation_id=event_dict["event_context"][
                            "execution_context"
                        ]["conversation_id"],
                        assistant_request_id=event_dict["assistant_request_id"],
                        event_type=event_dict["event_type"],
                        event_context=event_dict["event_context"],
                        data=event_dict["data"],
                        timestamp=event_dict["timestamp"],
                    )
                )
            session.bulk_save_objects(models)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to record events: {e}")
            raise e
        finally:
            session.close()

    def clear_events(self) -> None:
        raise NotImplementedError("Clearing events is not implemented for postgres.")

    def get_events(self) -> List[Event]:
        raise NotImplementedError("Getting all events is not implemented for postgres.")

    def get_event(self, event_id: str) -> Optional[Event]:
        """Get an event by ID."""
        session = self.Session()
        try:
            row = (
                session.query(EventModel)
                .filter(EventModel.event_id == event_id)
                .one_or_none()
            )
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
        finally:
            session.close()

    def get_agent_events(self, assistant_request_id: str) -> List[Event]:
        """
        Get all events for a given assistant_request_id.
        Again, naive approach of retrieving all and filtering in Python.
        """
        session = self.Session()
        try:
            row = (
                session.query(EventModel)
                .filter(EventModel.assistant_request_id == assistant_request_id)
                .all()
            )
            if len(row) == 0:
                return []

            events: List[Event] = []
            for r in row:
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
            logger.error(f"Failed to get event {assistant_request_id}: {e}")
            raise e
        finally:
            session.close()

    def get_conversation_events(self, conversation_id: str) -> List[Event]:
        """Get all events for a given conversation ID."""
        session = self.Session()
        try:
            row = (
                session.query(EventModel)
                .filter(EventModel.conversation_id == conversation_id)
                .all()
            )
            if len(row) == 0:
                return []

            events: List[Event] = []
            for r in row:
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
            logger.error(f"Failed to get event {conversation_id}: {e}")
            raise e
        finally:
            session.close()
