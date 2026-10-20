import json

import pytest

from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from tests.events.event_fixtures import HELLO_JSON
from tests.events.event_fixtures import INVOKE_CONTEXT_JSON
from tests.events.event_fixtures import TIMESTAMP
from tests.events.event_fixtures import TIMESTAMP_JSON
from tests.events.event_fixtures import hello
from tests.events.event_fixtures import invoke_context
from tests.events.event_fixtures import round_trip
from tests.events.event_fixtures import stored


@pytest.fixture
def publish_to_topic_event() -> PublishToTopicEvent:
    return PublishToTopicEvent(
        event_id="test_id",
        timestamp=TIMESTAMP,
        name="test_topic",
        publisher_name="test_node",
        publisher_type="test_type",
        offset=0,
        invoke_context=invoke_context(),
        consumed_event_ids=["1", "2"],
        data=[hello()],
    )


@pytest.fixture
def publish_to_topic_event_json() -> dict:
    return {
        "event_id": "test_id",
        "event_version": 2,
        "invoke_context": INVOKE_CONTEXT_JSON,
        "event_type": "PublishToTopic",
        "timestamp": TIMESTAMP_JSON,
        "name": "test_topic",
        "type": "NoneTopic",
        "offset": 0,
        "data": [HELLO_JSON],
        "emission_id": None,
        "consumed_event_ids": ["1", "2"],
        "publisher_name": "test_node",
        "publisher_type": "test_type",
    }


@pytest.fixture
def publish_to_topic_event_v1() -> dict:
    """The event as version 1 stored it (PublishToTopicEvent.to_dict)."""
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "PublishToTopic",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
            "name": "test_topic",
            "type": "NoneTopic",
            "offset": 0,
            "publisher_name": "test_node",
            "publisher_type": "test_type",
            "consumed_event_ids": ["1", "2"],
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "kwargs": {},
                "user_id": "",
            },
        },
        "data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null}]',
    }


def test_publish_to_topic_event_encodes_flat_json(
    publish_to_topic_event, publish_to_topic_event_json
):
    assert (
        default_event_codec.encode(publish_to_topic_event)
        == publish_to_topic_event_json
    )
    assert stored(publish_to_topic_event) == publish_to_topic_event_json


def test_publish_to_topic_event_round_trip(publish_to_topic_event):
    decoded = round_trip(publish_to_topic_event)
    assert type(decoded) is PublishToTopicEvent
    assert decoded == publish_to_topic_event


def test_publish_to_topic_event_decodes_version_1(
    publish_to_topic_event_v1, publish_to_topic_event
):
    decoded = default_event_codec.decode(publish_to_topic_event_v1)
    assert type(decoded) is PublishToTopicEvent
    assert decoded == publish_to_topic_event


def test_publish_to_topic_event_decodes_version_1_emission_id(
    publish_to_topic_event_v1, publish_to_topic_event
):
    # Version 1 wrote emission_id in the event context only when it was set.
    publish_to_topic_event_v1["event_context"]["emission_id"] = "source-emission"
    decoded = default_event_codec.decode(publish_to_topic_event_v1)
    assert decoded == publish_to_topic_event.model_copy(
        update={"emission_id": "source-emission"}
    )


@pytest.mark.parametrize("emission_id", [None, "source-emission"])
def test_publication_lineage_codec_round_trip(
    publish_to_topic_event: PublishToTopicEvent, emission_id: str | None
) -> None:
    event = publish_to_topic_event.model_copy(update={"emission_id": emission_id})
    encoded = stored(event)
    assert encoded["emission_id"] == emission_id
    decoded = default_event_codec.decode(encoded)
    assert isinstance(decoded, PublishToTopicEvent)
    assert decoded.emission_id == emission_id
    assert decoded == event


@pytest.mark.parametrize("emission_id", [None, "source-emission"])
def test_postgres_jsonb_publication_round_trip_without_database(
    publish_to_topic_event: PublishToTopicEvent, emission_id: str | None
) -> None:
    pytest.importorskip("sqlalchemy")
    from grafi.common.event_stores.event_store_postgres import EventModel
    from grafi.common.event_stores.event_store_postgres import EventStorePostgres

    event = publish_to_topic_event.model_copy(update={"emission_id": emission_id})
    # Exercise the real row encoder and decoder without creating engines or
    # making a database connection. Live SQL persistence is separate coverage.
    store = EventStorePostgres.__new__(EventStorePostgres)
    values = store._event_values(event)
    assert values["event_id"] == event.event_id
    assert values["event_version"] == "2"
    assert values["event_data"]["emission_id"] == emission_id
    row = EventModel(
        **{**values, "event_data": json.loads(json.dumps(values["event_data"]))}
    )
    assert store.codec.decode(row.event_data) == event
