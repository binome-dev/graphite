import pytest

from grafi.common.events.component_events import NodeRespondEvent
from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.topics.topic_types import TopicType
from tests.events.event_fixtures import HELLO_JSON
from tests.events.event_fixtures import INVOKE_CONTEXT_JSON
from tests.events.event_fixtures import REPLY_JSON
from tests.events.event_fixtures import TIMESTAMP
from tests.events.event_fixtures import TIMESTAMP_JSON
from tests.events.event_fixtures import hello
from tests.events.event_fixtures import invoke_context
from tests.events.event_fixtures import reply
from tests.events.event_fixtures import round_trip
from tests.events.event_fixtures import stored
from tests.events.node_events.test_node_event import consumed_events_json
from tests.events.node_events.test_node_event import consumed_events_v1
from tests.events.node_events.test_node_event import get_consumed_events


@pytest.fixture
def node_respond_event() -> NodeRespondEvent:
    return NodeRespondEvent(
        event_id="test_id",
        id="test_node_id",
        name="test_node",
        type="test_type",
        subscribed_topics=["test_topic_1", "test_topic_2"],
        publish_to_topics=["test_topic_3", "test_topic_4"],
        invoke_context=invoke_context(),
        input_data=get_consumed_events([hello()], invoke_context()),
        output_data=PublishToTopicEvent(
            event_id="test_id",
            timestamp=TIMESTAMP,
            invoke_context=invoke_context(),
            name="test_output_topic",
            type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
            publisher_name="test_node",
            publisher_type="test_type",
            consumed_event_ids=["test_id"],
            offset=3,
            data=[hello(), reply()],
        ),
        timestamp=TIMESTAMP,
    )


@pytest.fixture
def node_respond_event_json() -> dict:
    return {
        "event_id": "test_id",
        "event_version": 2,
        "invoke_context": INVOKE_CONTEXT_JSON,
        "event_type": "NodeRespond",
        "timestamp": TIMESTAMP_JSON,
        "id": "test_node_id",
        "name": "test_node",
        "type": "test_type",
        "subscribed_topics": ["test_topic_1", "test_topic_2"],
        "publish_to_topics": ["test_topic_3", "test_topic_4"],
        "input_data": consumed_events_json(),
        "output_data": {
            "event_id": "test_id",
            "event_version": 2,
            "invoke_context": INVOKE_CONTEXT_JSON,
            "event_type": "PublishToTopic",
            "timestamp": TIMESTAMP_JSON,
            "name": "test_output_topic",
            "type": "AgentOutputTopic",
            "offset": 3,
            "data": [HELLO_JSON, REPLY_JSON],
            "emission_id": None,
            "consumed_event_ids": ["test_id"],
            "publisher_name": "test_node",
            "publisher_type": "test_type",
        },
    }


@pytest.fixture
def node_respond_event_v1() -> dict:
    """The event as version 1 stored it (NodeRespondEvent.to_dict)."""
    return {
        "event_id": "test_id",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "NodeRespond",
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
                "user_id": "",
                "kwargs": {},
            },
        },
        "data": {
            "input_data": consumed_events_v1(),
            "output_data": {
                "event_context": {
                    "consumed_event_ids": ["test_id"],
                    "publisher_name": "test_node",
                    "publisher_type": "test_type",
                    "name": "test_output_topic",
                    "type": "AgentOutputTopic",
                    "offset": 3,
                    "invoke_context": {
                        "conversation_id": "conversation_id",
                        "invoke_id": "invoke_id",
                        "assistant_request_id": "assistant_request_id",
                        "user_id": "",
                        "kwargs": {},
                    },
                },
                "event_id": "test_id",
                "event_version": "1.0",
                "assistant_request_id": "assistant_request_id",
                "event_type": "PublishToTopic",
                "timestamp": "2009-02-13T23:31:30+00:00",
                "data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null}, {"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f6", "timestamp": 1737138526189605000, "content": "Hello, Grafi, I am doing well, thank you.", "refusal": null, "annotations": null, "audio": null, "role": "assistant", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null}]',
            },
        },
    }


def test_node_respond_event_encodes_flat_json(
    node_respond_event, node_respond_event_json
):
    assert default_event_codec.encode(node_respond_event) == node_respond_event_json
    assert stored(node_respond_event) == node_respond_event_json


def test_node_respond_event_round_trip(node_respond_event):
    decoded = round_trip(node_respond_event)
    assert type(decoded) is NodeRespondEvent
    assert decoded == node_respond_event
    assert type(decoded.output_data) is PublishToTopicEvent


def test_node_respond_event_decodes_version_1(
    node_respond_event_v1, node_respond_event
):
    decoded = default_event_codec.decode(node_respond_event_v1)
    assert type(decoded) is NodeRespondEvent
    assert decoded == node_respond_event
    assert type(decoded.output_data) is PublishToTopicEvent


def test_node_that_published_nothing_round_trip(node_respond_event):
    event = node_respond_event.model_copy(update={"output_data": None})
    assert stored(event)["output_data"] is None
    assert round_trip(event) == event


def test_node_that_published_nothing_decodes_version_1(
    node_respond_event_v1, node_respond_event
):
    node_respond_event_v1["data"]["output_data"] = None
    decoded = default_event_codec.decode(node_respond_event_v1)
    assert decoded == node_respond_event.model_copy(update={"output_data": None})
