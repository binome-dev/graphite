"""EventStorePostgres against a real database: run only when
GRAFI_TEST_POSTGRES_URL names one, such as a disposable container's
(postgresql://user:password@localhost:<port>/<db>).

Each test writes rows of its own conversation, and deletes them after."""

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any
from typing import AsyncIterator
from typing import Dict
from typing import List

import pytest
from sqlalchemy import delete

from grafi.common.event_stores.event_store_postgres import EventModel
from grafi.common.event_stores.event_store_postgres import EventStorePostgres
from grafi.common.events.event import Event
from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import EventSerializationError
from grafi.common.models.invoke_context import InvokeContext
from tests.events.event_fixtures import every_event
from tests.events.event_fixtures import request
from tests.events.event_fixtures import request_v1

POSTGRES_URL = os.getenv("GRAFI_TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="Set GRAFI_TEST_POSTGRES_URL to a disposable database to run.",
)


@asynccontextmanager
async def store_for(conversation_id: str) -> AsyncIterator[EventStorePostgres]:
    """A store on the database, whose rows of ``conversation_id`` are deleted
    afterwards."""
    store = EventStorePostgres(POSTGRES_URL)
    try:
        yield store
    finally:
        async with store._session() as session:
            await session.execute(
                delete(EventModel).where(EventModel.conversation_id == conversation_id)
            )
            await session.commit()
        await store.aclose()


def context(conversation_id: str) -> InvokeContext:
    return InvokeContext(
        conversation_id=conversation_id,
        invoke_id="invoke_id",
        assistant_request_id=conversation_id,
    )


def in_conversation(event: Event, conversation_id: str) -> Event:
    """``event`` with an id of its own, in the conversation ``conversation_id``."""
    return event.model_copy(
        update={
            "event_id": f"{conversation_id}-{event.event_id}",
            "invoke_context": context(conversation_id),
        }
    )


def v1_row(event_data: Dict[str, Any], conversation_id: str) -> EventModel:
    """A row as version 1 wrote it."""
    return EventModel(
        event_id=event_data["event_id"],
        conversation_id=conversation_id,
        assistant_request_id=conversation_id,
        event_type=event_data["event_type"],
        event_version="1.0",
        event_data=event_data,
        timestamp=default_event_codec.decode(event_data).timestamp.replace(tzinfo=None),
    )


@pytest.mark.asyncio
async def test_every_event_type_round_trips() -> None:
    conversation_id = uuid.uuid4().hex
    events = [in_conversation(event, conversation_id) for event in every_event()]
    async with store_for(conversation_id) as store:
        await store.record_events(events)
        assert await store.get_conversation_events(conversation_id) == events
        assert await store.get_agent_events(conversation_id) == events
        assert await store.get_event(events[4].event_id) == events[4]


@pytest.mark.asyncio
async def test_recording_is_idempotent() -> None:
    conversation_id = uuid.uuid4().hex
    event = in_conversation(request(), conversation_id)
    async with store_for(conversation_id) as store:
        await store.record_event(event)
        await store.record_event(event)
        await store.record_events([event, event])
        assert await store.get_conversation_events(conversation_id) == [event]


@pytest.mark.asyncio
async def test_topic_events_are_found_in_rows_of_either_version() -> None:
    conversation_id = uuid.uuid4().hex
    topic = f"topic-{conversation_id}"
    version_1: Dict[str, Any] = request_v1()
    version_1["event_id"] = f"{conversation_id}-v1"
    version_1["event_context"]["name"] = topic
    version_1["event_context"]["offset"] = 0
    version_1["event_context"]["invoke_context"] = context(conversation_id).model_dump()
    version_2 = in_conversation(request(), conversation_id).model_copy(
        update={"event_id": f"{conversation_id}-v2", "name": topic, "offset": 1}
    )
    async with store_for(conversation_id) as store:
        await store.record_event(version_2)
        async with store._session() as session:
            session.add(v1_row(version_1, conversation_id))
            await session.commit()

        found: List[Event] = await store.get_topic_events(topic, [0, 1])

        assert found == [default_event_codec.decode(version_1), version_2]
        assert all(type(event) is PublishToTopicEvent for event in found)
        assert await store.get_topic_events(topic, [1]) == [version_2]
        assert await store.get_topic_events(topic, [2]) == []


@pytest.mark.asyncio
async def test_an_undecodable_row_raises() -> None:
    conversation_id = uuid.uuid4().hex
    event = in_conversation(request(), conversation_id)
    async with store_for(conversation_id) as store:
        await store.record_event(event)
        async with store._session() as session:
            row = EventModel(**store._event_values(event))
            row.event_id = f"{conversation_id}-unknown"
            row.event_data = {**row.event_data, "event_type": "Unknown"}
            session.add(row)
            await session.commit()

        with pytest.raises(EventSerializationError, match="Unknown"):
            await store.get_conversation_events(conversation_id)
