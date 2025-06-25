import pytest

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message


@pytest.fixture
def consume_from_topic_event() -> ConsumeFromTopicEvent:
    return ConsumeFromTopicEvent(
        event_id="test_id",
        event_type="ConsumeFromTopic",
        timestamp="2009-02-13T23:31:30+00:00",
        topic_name="test_topic",
        consumer_name="test_node",
        consumer_type="test_type",
        offset=0,
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
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
def consume_from_topic_event_message() -> ConsumeFromTopicEvent:
    return ConsumeFromTopicEvent(
        event_id="test_id",
        event_type="ConsumeFromTopic",
        timestamp="2009-02-13T23:31:30+00:00",
        topic_name="test_topic",
        consumer_name="test_node",
        consumer_type="test_type",
        offset=0,
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
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
def consume_from_topic_event_dict():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "ConsumeFromTopic",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            "topic_name": "test_topic",
            "offset": 0,
            "consumer_name": "test_node",
            "consumer_type": "test_type",
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
def consume_from_topic_event_dict_message():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "ConsumeFromTopic",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            "topic_name": "test_topic",
            "offset": 0,
            "consumer_name": "test_node",
            "consumer_type": "test_type",
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}]',
    }


def test_consume_from_topic_event_to_dict(
    consume_from_topic_event: ConsumeFromTopicEvent, consume_from_topic_event_dict
):
    assert consume_from_topic_event.to_dict() == consume_from_topic_event_dict


def test_consume_from_topic_event_from_dict(
    consume_from_topic_event_dict, consume_from_topic_event
):
    assert (
        ConsumeFromTopicEvent.from_dict(consume_from_topic_event_dict)
        == consume_from_topic_event
    )


def test_consume_from_topic_event_to_dict_message(
    consume_from_topic_event_message: ConsumeFromTopicEvent,
    consume_from_topic_event_dict_message,
):
    assert (
        consume_from_topic_event_message.to_dict()
        == consume_from_topic_event_dict_message
    )


def test_consume_from_topic_event_from_dict_message(
    consume_from_topic_event_dict_message, consume_from_topic_event_message
):
    assert (
        ConsumeFromTopicEvent.from_dict(consume_from_topic_event_dict_message)
        == consume_from_topic_event_message
    )
