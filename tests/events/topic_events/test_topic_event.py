import pytest
from pydantic import ValidationError

from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.topics.topic_types import TopicType
from tests.events.event_fixtures import HELLO_JSON
from tests.events.event_fixtures import INVOKE_CONTEXT_JSON
from tests.events.event_fixtures import TIMESTAMP
from tests.events.event_fixtures import TIMESTAMP_JSON
from tests.events.event_fixtures import hello
from tests.events.event_fixtures import invoke_context
from tests.events.event_fixtures import round_trip
from tests.events.event_fixtures import stored


@pytest.fixture
def topic_event() -> TopicEvent:
    return TopicEvent(
        event_id="test_id",
        timestamp=TIMESTAMP,
        invoke_context=invoke_context(),
        name="test_topic",
        type=TopicType.DEFAULT_TOPIC_TYPE,
        offset=0,
        data=[hello()],
    )


@pytest.fixture
def topic_event_json() -> dict:
    return {
        "event_id": "test_id",
        "event_version": 2,
        "invoke_context": INVOKE_CONTEXT_JSON,
        "event_type": "TopicEvent",
        "timestamp": TIMESTAMP_JSON,
        "name": "test_topic",
        "type": "Topic",
        "offset": 0,
        "data": [HELLO_JSON],
    }


def test_topic_event_encodes_flat_json(topic_event, topic_event_json):
    assert default_event_codec.encode(topic_event) == topic_event_json
    assert stored(topic_event) == topic_event_json


def test_topic_event_round_trip(topic_event):
    decoded = round_trip(topic_event)
    assert type(decoded) is TopicEvent
    assert decoded == topic_event


def test_topic_event_without_messages_round_trip(topic_event):
    event = topic_event.model_copy(update={"data": []})
    assert stored(event)["data"] == []
    assert round_trip(event) == event


def test_topic_event_defaults_round_trip():
    event = TopicEvent(invoke_context=invoke_context(), data=[])
    assert round_trip(event) == event
    assert stored(event)["event_type"] == "TopicEvent"
    assert stored(event)["type"] == "NoneTopic"
    assert stored(event)["offset"] == -1


def test_topic_event_is_only_of_its_own_type():
    with pytest.raises(ValidationError, match="A TopicEvent has event_type"):
        TopicEvent(
            event_type="ConsumeFromTopic", invoke_context=invoke_context(), data=[]
        )
