"""EventStorePostgres keeps each event as its JSON form (version 2) in a row,
and reads rows of either version back; no database is used here."""

import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import List

import pytest
from sqlalchemy.dialects import postgresql

from grafi.common.event_stores.event_store_postgres import EventModel
from grafi.common.event_stores.event_store_postgres import EventStorePostgres
from grafi.common.events.event import Event
from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.exceptions import EventPersistenceError
from grafi.common.exceptions import EventSerializationError
from tests.events.event_fixtures import every_event
from tests.events.event_fixtures import request
from tests.events.event_fixtures import request_v1


class _Result:
    def __init__(self, rows: List[EventModel]) -> None:
        self._rows = rows

    def scalars(self) -> "_Result":
        return self

    def all(self) -> List[EventModel]:
        return self._rows


class _Session:
    """Returns the rows given for every query, and records the statements."""

    def __init__(self, rows: List[EventModel], fail: bool = False) -> None:
        self.rows = rows
        self.fail = fail
        self.statements: List[Any] = []

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def execute(self, statement: Any, *params: Any) -> _Result:
        if self.fail:
            raise OSError("connection lost")
        self.statements.append(statement)
        return _Result(self.rows)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def store_with(session: _Session) -> EventStorePostgres:
    store = EventStorePostgres.__new__(EventStorePostgres)  # No database.
    store.AsyncSession = lambda: session  # type: ignore[assignment]
    store._table_ready = True
    return store


def row(event_data: dict) -> EventModel:
    """A row as the database returns it: its JSON read back."""
    return EventModel(event_data=json.loads(json.dumps(event_data)))


def sql(statement: Any) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


@pytest.mark.parametrize("event", every_event(), ids=lambda event: event.event_id)
def test_a_row_holds_the_events_json_form(event: Event) -> None:
    values = store_with(_Session([]))._event_values(event)
    assert values == {
        "event_id": event.event_id,
        "conversation_id": "conversation_id",
        "assistant_request_id": "assistant_request_id",
        "event_type": event.event_type.value,
        "event_version": "2",
        "event_data": default_event_codec.encode(event),
        "timestamp": datetime(2009, 2, 13, 23, 31, 30),
    }
    assert "event_context" not in values["event_data"]
    assert default_event_codec.decode(row(values["event_data"]).event_data) == event


def test_a_row_timestamp_is_naive_utc() -> None:
    dubai = timezone(timedelta(hours=4))
    event = request().model_copy(
        update={"timestamp": datetime(2026, 1, 1, 12, 0, tzinfo=dubai)}
    )
    values = store_with(_Session([]))._event_values(event)
    assert values["timestamp"] == datetime(2026, 1, 1, 8, 0)
    assert values["timestamp"].tzinfo is None


@pytest.mark.asyncio
async def test_rows_of_either_version_are_read() -> None:
    session = _Session([row(request_v1()), row(default_event_codec.encode(request()))])
    events = await store_with(session).get_events()
    assert events == [request(), request()]
    assert all(type(event) is PublishToTopicEvent for event in events)


@pytest.mark.asyncio
async def test_every_event_type_is_read_back() -> None:
    events = every_event()
    session = _Session([row(default_event_codec.encode(event)) for event in events])
    assert await store_with(session).get_events() == events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "read",
    [
        lambda store: store.get_events(),
        lambda store: store.get_event("test_id"),
        lambda store: store.get_agent_events("assistant_request_id"),
        lambda store: store.get_conversation_events("conversation_id"),
        lambda store: store.get_topic_events("test_output_topic", [-1]),
    ],
    ids=["events", "event", "agent", "conversation", "topic"],
)
async def test_an_undecodable_row_raises_a_serialization_error(read: Any) -> None:
    # Not hidden as a persistence failure, nor skipped.
    undecodable = {**default_event_codec.encode(request()), "event_type": "Unknown"}
    session = _Session([row(default_event_codec.encode(request())), row(undecodable)])
    with pytest.raises(EventSerializationError, match="Unknown"):
        await read(store_with(session))


@pytest.mark.asyncio
async def test_a_row_of_a_newer_version_raises_a_serialization_error() -> None:
    newer = {**default_event_codec.encode(request()), "event_version": 3}
    with pytest.raises(EventSerializationError, match="version 3"):
        await store_with(_Session([row(newer)])).get_events()


@pytest.mark.asyncio
async def test_a_failed_query_raises_a_persistence_error() -> None:
    with pytest.raises(EventPersistenceError) as raised:
        await store_with(_Session([], fail=True)).get_topic_events("t", [0])
    assert raised.value.operation == "get_topic_events:t"
    assert isinstance(raised.value.__cause__, OSError)


@pytest.mark.asyncio
async def test_get_event_of_an_unknown_id_is_none() -> None:
    assert await store_with(_Session([])).get_event("missing") is None


@pytest.mark.asyncio
async def test_topic_events_match_rows_of_either_version() -> None:
    session = _Session([row(request_v1()), row(default_event_codec.encode(request()))])
    events = await store_with(session).get_topic_events("test_output_topic", [-1, 2])
    assert events == [request(), request()]

    [statement] = session.statements
    query = sql(statement)
    # The name and offset are read at the top level (version 2), or under
    # event_context (version 1).
    name = (
        "coalesce((events.event_data -> 'event_context') ->> 'name', "
        "events.event_data ->> 'name') = 'test_output_topic'"
    )
    offset = (
        "CAST(coalesce((events.event_data -> 'event_context') ->> 'offset', "
        "events.event_data ->> 'offset') AS INTEGER)"
    )
    assert name in query
    assert f"{offset} IN (-1, 2)" in query
    assert query.endswith(f"ORDER BY {offset}")
    assert "events.event_type IN ('PublishToTopic', 'TopicEvent')" in query


@pytest.mark.asyncio
async def test_topic_events_of_no_offsets_need_no_query() -> None:
    session = _Session([], fail=True)
    assert await store_with(session).get_topic_events("t", []) == []


@pytest.mark.asyncio
async def test_an_unencodable_event_is_not_recorded() -> None:
    session = _Session([])
    event = request().model_copy(
        update={
            "invoke_context": request().invoke_context.model_copy(
                update={"kwargs": {"client": object()}}
            )
        }
    )
    with pytest.raises(EventSerializationError, match="cannot be encoded"):
        await store_with(session).record_events([request(), event])
    assert session.statements == []
