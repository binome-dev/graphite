from typing import List

import pytest

from grafi.common.events.event import EventType
from grafi.common.events.node_events.node_event import NodeEvent
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message


def get_consumed_events(messages: List[Message]) -> List[ConsumeFromTopicEvent]:
    return [
        ConsumeFromTopicEvent(
            event_id="test_id",
            topic_name="test_topic",
            node_id="test_node_id",
            consumer_name="test_node",
            consumer_type="test_type",
            execution_context=ExecutionContext(
                conversation_id="conversation_id",
                execution_id="execution_id",
                assistant_request_id="assistant_request_id",
            ),
            data=[message],
            offset=-1,
            timestamp="2009-02-13T23:31:30+00:00",
        )
        for message in messages
    ]


@pytest.fixture
def execution_context():
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id="execution_id",
        assistant_request_id="assistant_request_id",
    )


@pytest.fixture
def node_event(execution_context) -> NodeEvent:
    return NodeEvent(
        event_id="test_id",
        event_type=EventType.NODE_INVOKE,
        node_id="test_node_id",
        node_name="test_node",
        node_type="test_type",
        subscribed_topics=["test_topic_1", "test_topic_2"],
        publish_to_topics=["test_topic_3", "test_topic_4"],
        execution_context=execution_context,
        timestamp="2009-02-13T23:31:30+00:00",
    )


@pytest.fixture
def node_event_dict():
    return {
        "event_id": "test_id",
        "event_type": "NodeInvoke",
        "assistant_request_id": "assistant_request_id",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
            "node_id": "test_node_id",
            "subscribed_topics": ["test_topic_1", "test_topic_2"],
            "publish_to_topics": ["test_topic_3", "test_topic_4"],
            "node_name": "test_node",
            "node_type": "test_type",
            "execution_context": {
                "conversation_id": "conversation_id",
                "execution_id": "execution_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
    }


def test_node_event_dict(node_event: NodeEvent, node_event_dict):
    assert node_event.node_event_dict() == node_event_dict


def test_node_event_base(node_event_dict, node_event):
    assert NodeEvent.node_event_base(node_event_dict) == node_event
