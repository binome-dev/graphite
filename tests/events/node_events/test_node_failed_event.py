import pytest

from grafi.common.events.component_events import NodeFailedEvent
from grafi.common.events.event_codec import default_event_codec
from tests.events.event_fixtures import INVOKE_CONTEXT_JSON
from tests.events.event_fixtures import TIMESTAMP
from tests.events.event_fixtures import TIMESTAMP_JSON
from tests.events.event_fixtures import hello
from tests.events.event_fixtures import invoke_context
from tests.events.event_fixtures import round_trip
from tests.events.event_fixtures import stored
from tests.events.node_events.test_node_event import consumed_events_json
from tests.events.node_events.test_node_event import consumed_events_v1
from tests.events.node_events.test_node_event import get_consumed_events


@pytest.fixture
def node_failed_event() -> NodeFailedEvent:
    return NodeFailedEvent(
        event_id="test_id",
        id="test_node_id",
        name="test_node",
        type="test_type",
        subscribed_topics=["test_topic_1", "test_topic_2"],
        publish_to_topics=["test_topic_3", "test_topic_4"],
        invoke_context=invoke_context(),
        input_data=get_consumed_events([hello()], invoke_context()),
        error="error",
        timestamp=TIMESTAMP,
    )


@pytest.fixture
def node_failed_event_json() -> dict:
    return {
        "event_id": "test_id",
        "event_version": 2,
        "invoke_context": INVOKE_CONTEXT_JSON,
        "event_type": "NodeFailed",
        "timestamp": TIMESTAMP_JSON,
        "id": "test_node_id",
        "name": "test_node",
        "type": "test_type",
        "subscribed_topics": ["test_topic_1", "test_topic_2"],
        "publish_to_topics": ["test_topic_3", "test_topic_4"],
        "input_data": consumed_events_json(),
        "error": "error",
        "error_details": None,
    }


@pytest.fixture
def node_failed_event_v1() -> dict:
    """The event as version 1 stored it (NodeFailedEvent.to_dict)."""
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "NodeFailed",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
            "id": "test_node_id",
            "subscribed_topics": ["test_topic_1", "test_topic_2"],
            "publish_to_topics": ["test_topic_3", "test_topic_4"],
            "name": "test_node",
            "type": "test_type",
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "kwargs": {},
                "user_id": "",
            },
        },
        "data": {"input_data": consumed_events_v1(), "error": "error"},
    }


def test_node_failed_event_encodes_flat_json(node_failed_event, node_failed_event_json):
    assert default_event_codec.encode(node_failed_event) == node_failed_event_json
    assert stored(node_failed_event) == node_failed_event_json


def test_node_failed_event_round_trip(node_failed_event):
    decoded = round_trip(node_failed_event)
    assert type(decoded) is NodeFailedEvent
    assert decoded == node_failed_event


def test_node_failed_event_decodes_version_1(node_failed_event_v1, node_failed_event):
    decoded = default_event_codec.decode(node_failed_event_v1)
    assert type(decoded) is NodeFailedEvent
    assert decoded == node_failed_event
