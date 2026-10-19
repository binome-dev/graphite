"""EventStorePostgres writes a batch of any size with one statement, executed
for every row in one transaction."""

from typing import Any
from typing import List

import pytest

from grafi.common.event_stores.event_store_postgres import EventStorePostgres
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


class Session:
    """Records the statements executed and whether the transaction committed."""

    def __init__(self, fail: bool = False) -> None:
        self.rows: List[int] = []
        self.committed = self.rolled_back = False
        self._fail = fail

    async def __aenter__(self) -> "Session":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def execute(self, statement: Any, params: List[Any]) -> None:
        if self._fail:
            raise OSError("connection lost")
        self.rows.append(len(params))

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def store_with(session: Session) -> EventStorePostgres:
    store = EventStorePostgres.__new__(EventStorePostgres)  # No database.
    store.AsyncSession = lambda: session  # type: ignore[assignment]
    return store


def events(count: int) -> List[PublishToTopicEvent]:
    context = InvokeContext(
        conversation_id="c", invoke_id="i", assistant_request_id="r"
    )
    return [
        PublishToTopicEvent(
            name="t",
            offset=offset,
            invoke_context=context,
            data=[Message(role="assistant", content="x")],
        )
        for offset in range(count)
    ]


@pytest.mark.asyncio
async def test_a_large_batch_is_written_in_one_transaction() -> None:
    session = Session()
    await store_with(session).record_events(events(6000))
    assert session.rows == [6000]
    assert session.committed


@pytest.mark.asyncio
async def test_a_failed_batch_is_rolled_back() -> None:
    session = Session(fail=True)
    with pytest.raises(Exception, match="Failed to record events"):
        await store_with(session).record_events(events(10))
    assert session.rolled_back and not session.committed
