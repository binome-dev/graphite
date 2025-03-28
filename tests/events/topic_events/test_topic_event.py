import pytest

from grafi.common.events.event import EVENT_CONTEXT
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message


@pytest.fixture
def topic_event() -> TopicEvent:
    return TopicEvent(
        event_id="test_id",
        event_type="TopicEvent",
        timestamp="2009-02-13T23:31:30+00:00",
        topic_name="test_topic",
        offset=0,
        execution_context=ExecutionContext(
            conversation_id="conversation_id",
            execution_id="execution_id",
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
def topic_event_message() -> TopicEvent:
    return TopicEvent(
        event_id="test_id",
        event_type="TopicEvent",
        timestamp="2009-02-13T23:31:30+00:00",
        topic_name="test_topic",
        offset=0,
        execution_context=ExecutionContext(
            conversation_id="conversation_id",
            execution_id="execution_id",
            assistant_request_id="assistant_request_id",
        ),
        data=Message(
            message_id="ea72df51439b42e4a43b217c9bca63f5",
            timestamp=1737138526189505000,
            role="user",
            content="Hello, my name is Grafi, how are you doing?",
            name=None,
            functions=None,
            function_call=None,
        ),
    )


@pytest.fixture
def topic_event_dict():
    return {
        "event_id": "test_id",
        "event_type": "TopicEvent",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            "topic_name": "test_topic",
            "offset": 0,
            "execution_context": {
                "conversation_id": "conversation_id",
                "execution_id": "execution_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": '[{"content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "role": "user", "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "tool_call_id": null, "tools": null, "functions": null}]',
    }


@pytest.fixture
def topic_event_dict_message():
    return {
        "event_id": "test_id",
        "event_type": "TopicEvent",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        EVENT_CONTEXT: {
            "topic_name": "test_topic",
            "offset": 0,
            "execution_context": {
                "conversation_id": "conversation_id",
                "execution_id": "execution_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": '{"content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "role": "user", "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "tool_call_id": null, "tools": null, "functions": null}',
    }


def test_topic_event_dict(topic_event: TopicEvent, topic_event_dict):
    assert topic_event.topic_event_dict() == topic_event_dict


def test_topic_event_base(topic_event_dict, topic_event):
    assert TopicEvent.topic_event_base(topic_event_dict) == topic_event


def test_topic_event_dict_message(
    topic_event_message: TopicEvent, topic_event_dict_message
):
    assert topic_event_message.topic_event_dict() == topic_event_dict_message


def test_topic_event_base_message(topic_event_dict_message, topic_event_message):
    assert TopicEvent.topic_event_base(topic_event_dict_message) == topic_event_message
