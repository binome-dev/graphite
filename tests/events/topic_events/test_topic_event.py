from datetime import datetime
from datetime import timezone

import pytest

from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.invoke_context import InvokeContext


@pytest.fixture
def topic_event() -> TopicEvent:
    return TopicEvent(
        event_id="test_id",
        event_type="TopicEvent",
        timestamp="2009-02-13T23:31:30+00:00",
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
        topic_name="test_topic",
        offset=0,
        data=[],
    )


@pytest.fixture
def topic_event_message() -> TopicEvent:
    return TopicEvent(
        event_id="test_id",
        event_type="TopicEvent",
        timestamp="2009-02-13T23:31:30+00:00",
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
        topic_name="test_topic",
        offset=0,
        data=[],
    )


@pytest.fixture
def topic_event_dict():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "TopicEvent",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
    }


@pytest.fixture
def topic_event_dict_message():
    return {
        "event_version": "1.0",
        "event_id": "test_id",
        "event_type": "TopicEvent",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
    }


def test_event_dict(topic_event: TopicEvent, topic_event_dict):
    assert topic_event.event_dict() == topic_event_dict


def test_topic_event_base(topic_event_dict, topic_event):
    assert TopicEvent.event_base(topic_event_dict)[0] == "test_id"
    assert TopicEvent.event_base(topic_event_dict)[1].value == "TopicEvent"
    assert TopicEvent.event_base(topic_event_dict)[2] == datetime(
        2009, 2, 13, 23, 31, 30, tzinfo=timezone.utc
    )


def test_topic_event_dict_message(
    topic_event_message: TopicEvent, topic_event_dict_message
):
    assert topic_event_message.event_dict() == topic_event_dict_message
