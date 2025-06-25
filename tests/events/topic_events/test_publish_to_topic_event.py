import pytest

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


@pytest.fixture
def publish_to_topic_event() -> PublishToTopicEvent:
    return PublishToTopicEvent(
        event_id="test_id",
        event_type="PublishToTopic",
        timestamp="2009-02-13T23:31:30+00:00",
        topic_name="test_topic",
        publisher_name="test_node",
        publisher_type="test_type",
        offset=0,
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
        consumed_event_ids=["1", "2"],
        data=[
            Message(
                message_id="ea72df51439b42e4a43b217c9bca63f5",
                timestamp=1737138526189505000,
                role="user",
                content="Hello, my name is Grafi, how are you doing?",
                name=None,
                functions=None,
                function_call=None,
            )
        ],
    )


@pytest.fixture
def publish_to_topic_event_message() -> PublishToTopicEvent:
    return PublishToTopicEvent(
        event_id="test_id",
        event_type="PublishToTopic",
        timestamp="2009-02-13T23:31:30+00:00",
        topic_name="test_topic",
        publisher_name="test_node",
        publisher_type="test_type",
        offset=0,
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
        consumed_event_ids=["1", "2"],
        data=[
            Message(
                message_id="ea72df51439b42e4a43b217c9bca63f5",
                timestamp=1737138526189505000,
                role="user",
                content="Hello, my name is Grafi, how are you doing?",
                name=None,
                functions=None,
                function_call=None,
            )
        ],
    )


@pytest.fixture
def publish_to_topic_event_dict():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "PublishToTopic",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            "topic_name": "test_topic",
            "offset": 0,
            "publisher_name": "test_node",
            "publisher_type": "test_type",
            "consumed_event_ids": ["1", "2"],
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}]',
    }


@pytest.fixture
def publish_to_topic_event_dict_message():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "PublishToTopic",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            "topic_name": "test_topic",
            "offset": 0,
            "publisher_name": "test_node",
            "publisher_type": "test_type",
            "consumed_event_ids": ["1", "2"],
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}]',
    }


def test_publish_to_topic_event_to_dict(
    publish_to_topic_event: PublishToTopicEvent, publish_to_topic_event_dict
):
    assert publish_to_topic_event.to_dict() == publish_to_topic_event_dict


def test_publish_to_topic_event_from_dict(
    publish_to_topic_event_dict, publish_to_topic_event
):
    assert (
        PublishToTopicEvent.from_dict(publish_to_topic_event_dict)
        == publish_to_topic_event
    )


def test_publish_to_topic_event_to_dict_message(
    publish_to_topic_event_message: PublishToTopicEvent,
    publish_to_topic_event_dict_message,
):
    assert (
        publish_to_topic_event_message.to_dict() == publish_to_topic_event_dict_message
    )


def test_publish_to_topic_event_from_dict_message(
    publish_to_topic_event_dict_message, publish_to_topic_event_message
):
    assert (
        PublishToTopicEvent.from_dict(publish_to_topic_event_dict_message)
        == publish_to_topic_event_message
    )
