import pytest

from grafi.common.events.event import EventType
from grafi.common.events.node_events.node_invoke_event import NodeInvokeEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from tests.events.node_events.test_node_event import get_consumed_events


@pytest.fixture
def invoke_context():
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id="invoke_id",
        assistant_request_id="assistant_request_id",
    )


@pytest.fixture
def node_invoke_event(invoke_context) -> NodeInvokeEvent:
    return NodeInvokeEvent(
        event_id="test_id",
        event_type=EventType.NODE_INVOKE,
        node_id="test_node_id",
        node_name="test_node",
        node_type="test_type",
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
            ]
        ),
        timestamp="2009-02-13T23:31:30+00:00",
    )


@pytest.fixture
def node_invoke_event_dict():
    return {
        "event_version": "1.0",
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
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
            },
        },
        "data": {
            "input_data": [
                {
                    "event_context": {
                        "consumer_name": "test_node",
                        "consumer_type": "test_type",
                        "topic_name": "test_topic",
                        "offset": -1,
                        "invoke_context": {
                            "conversation_id": "conversation_id",
                            "invoke_id": "invoke_id",
                            "assistant_request_id": "assistant_request_id",
                            "user_id": "",
                        },
                    },
                    "event_id": "test_id",
                    "event_version": "1.0",
                    "assistant_request_id": "assistant_request_id",
                    "event_type": "ConsumeFromTopic",
                    "timestamp": "2009-02-13T23:31:30+00:00",
                    "data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}]',
                }
            ]
        },
    }


def test_node_invoke_event_to_dict(
    node_invoke_event: NodeInvokeEvent, node_invoke_event_dict
):
    assert node_invoke_event.to_dict() == node_invoke_event_dict


def test_node_invoke_event_from_dict(node_invoke_event_dict, node_invoke_event):
    assert NodeInvokeEvent.from_dict(node_invoke_event_dict) == node_invoke_event
