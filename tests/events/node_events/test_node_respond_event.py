from typing import Any

import pytest

from grafi.common.events.component_events import NodeRespondEvent
from grafi.common.events.event import EventType
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_types import TopicType
from tests.events.node_events.test_node_event import get_consumed_events


@pytest.fixture
def invoke_context():
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id="invoke_id",
        assistant_request_id="assistant_request_id",
    )


@pytest.fixture
def node_respond_event(invoke_context) -> Any:
    return NodeRespondEvent(
        event_id="test_id",
        event_type=EventType.NODE_INVOKE,
        id="test_node_id",
        name="test_node",
        type="test_type",
        subscribed_topics=["test_topic_1", "test_topic_2"],
        publish_to_topics=["test_topic_3", "test_topic_4"],
        invoke_context=invoke_context,
        input_data=get_consumed_events(
            [
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
            invoke_context,
        ),
        output_data=PublishToTopicEvent(
            event_id="test_id",
            timestamp="2009-02-13T23:31:30+00:00",
            invoke_context=invoke_context,
            name="test_output_topic",
            type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
            publisher_name="test_node",
            publisher_type="test_type",
            consumed_event_ids=["test_id"],
            offset=3,
            data=[
                Message(
                    message_id="ea72df51439b42e4a43b217c9bca63f5",
                    timestamp=1737138526189505000,
                    role="user",
                    content="Hello, my name is Grafi, how are you doing?",
                    name=None,
                    functions=None,
                    function_call=None,
                ),
                Message(
                    message_id="ea72df51439b42e4a43b217c9bca63f6",
                    timestamp=1737138526189605000,
                    role="assistant",
                    content="Hello, Grafi, I am doing well, thank you.",
                    name=None,
                    functions=None,
                    function_call=None,
                ),
            ],
        ),
        timestamp="2009-02-13T23:31:30+00:00",
    )


@pytest.fixture
def node_respond_event_dict():
    return {
        "event_id": "test_id",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "NodeInvoke",
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
            "input_data": [
                {
                    "event_context": {
                        "consumer_name": "test_node",
                        "consumer_type": "test_type",
                        "name": "test_topic",
                        "type": "AgentOutputTopic",
                        "offset": -1,
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
                    "event_type": "ConsumeFromTopic",
                    "timestamp": "2009-02-13T23:31:30+00:00",
                    "data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}]',
                }
            ],
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
                "data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}, {"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f6", "timestamp": 1737138526189605000, "content": "Hello, Grafi, I am doing well, thank you.", "refusal": null, "annotations": null, "audio": null, "role": "assistant", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}]',
            },
        },
    }


def test_node_respond_event_to_dict(node_respond_event, node_respond_event_dict):
    assert node_respond_event.to_dict() == node_respond_event_dict


def test_node_respond_event_from_dict(node_respond_event_dict, node_respond_event):
    assert NodeRespondEvent.from_dict(node_respond_event_dict) == node_respond_event
