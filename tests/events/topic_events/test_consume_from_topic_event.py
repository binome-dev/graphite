import pytest

from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from tests.events.event_fixtures import HELLO_JSON
from tests.events.event_fixtures import INVOKE_CONTEXT_JSON
from tests.events.event_fixtures import TIMESTAMP
from tests.events.event_fixtures import TIMESTAMP_JSON
from tests.events.event_fixtures import hello
from tests.events.event_fixtures import invoke_context
from tests.events.event_fixtures import round_trip
from tests.events.event_fixtures import stored


@pytest.fixture
def consume_from_topic_event() -> ConsumeFromTopicEvent:
    return ConsumeFromTopicEvent(
        event_id="test_id",
        timestamp=TIMESTAMP,
        name="test_topic",
        consumer_name="test_node",
        consumer_type="test_type",
        offset=0,
        invoke_context=invoke_context(),
        data=[hello()],
    )


@pytest.fixture
def consume_from_topic_event_json() -> dict:
    return {
        "event_id": "test_id",
        "event_version": 2,
        "invoke_context": INVOKE_CONTEXT_JSON,
        "event_type": "ConsumeFromTopic",
        "timestamp": TIMESTAMP_JSON,
        "name": "test_topic",
        "type": "NoneTopic",
        "offset": 0,
        "data": [HELLO_JSON],
        "consumer_name": "test_node",
        "consumer_type": "test_type",
    }


@pytest.fixture
def consume_from_topic_event_v1() -> dict:
    """The event as version 1 stored it (ConsumeFromTopicEvent.to_dict)."""
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "ConsumeFromTopic",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
            "name": "test_topic",
            "type": "NoneTopic",
            "offset": 0,
            "consumer_name": "test_node",
            "consumer_type": "test_type",
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


def test_consume_from_topic_event_encodes_flat_json(
    consume_from_topic_event, consume_from_topic_event_json
):
    assert (
        default_event_codec.encode(consume_from_topic_event)
        == consume_from_topic_event_json
    )
    assert stored(consume_from_topic_event) == consume_from_topic_event_json


def test_consume_from_topic_event_round_trip(consume_from_topic_event):
    decoded = round_trip(consume_from_topic_event)
    assert type(decoded) is ConsumeFromTopicEvent
    assert decoded == consume_from_topic_event


def test_consume_from_topic_event_decodes_version_1(
    consume_from_topic_event_v1, consume_from_topic_event
):
    decoded = default_event_codec.decode(consume_from_topic_event_v1)
    assert type(decoded) is ConsumeFromTopicEvent
    assert decoded == consume_from_topic_event
    assert decoded.event_version == 2
