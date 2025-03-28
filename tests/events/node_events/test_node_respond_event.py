import pytest

from grafi.common.events.event import EventType
from grafi.common.events.node_events.node_respond_event import NodeRespondEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Message
from tests.events.node_events.test_node_event import get_consumed_events


@pytest.fixture
def execution_context():
    return ExecutionContext(
        conversation_id="conversation_id",
        execution_id="execution_id",
        assistant_request_id="assistant_request_id",
    )


@pytest.fixture
def node_respond_event(execution_context) -> NodeRespondEvent:
    return NodeRespondEvent(
        event_id="test_id",
        event_type=EventType.NODE_INVOKE,
        node_id="test_node_id",
        node_name="test_node",
        node_type="test_type",
        subscribed_topics=["test_topic_1", "test_topic_2"],
        publish_to_topics=["test_topic_3", "test_topic_4"],
        execution_context=execution_context,
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
        output_data=[
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
        timestamp="2009-02-13T23:31:30+00:00",
    )


@pytest.fixture
def node_respond_event_dict():
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
        "data": {
            "input_data": [
                {
                    "event_id": "test_id",
                    "assistant_request_id": "assistant_request_id",
                    "event_type": "ConsumeFromTopic",
                    "timestamp": "2009-02-13T23:31:30+00:00",
                    "consumer_name": "test_node",
                    "consumer_type": "test_type",
                    "event_context": {
                        "topic_name": "test_topic",
                        "offset": -1,
                        "execution_context": {
                            "conversation_id": "conversation_id",
                            "execution_id": "execution_id",
                            "assistant_request_id": "assistant_request_id",
                            "user_id": "",
                        },
                    },
                    "data": '[{"content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "role": "user", "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "tool_call_id": null, "tools": null, "functions": null}]',
                }
            ],
            "output_data": '[{"content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "role": "user", "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "tool_call_id": null, "tools": null, "functions": null}, {"content": "Hello, Grafi, I am doing well, thank you.", "refusal": null, "role": "assistant", "audio": null, "function_call": null, "tool_calls": null, "name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f6", "timestamp": 1737138526189605000, "tool_call_id": null, "tools": null, "functions": null}]',
        },
    }


def test_node_respond_event_to_dict(
    node_respond_event: NodeRespondEvent, node_respond_event_dict
):
    assert node_respond_event.to_dict() == node_respond_event_dict


def test_node_respond_event_from_dict(node_respond_event_dict, node_respond_event):
    assert NodeRespondEvent.from_dict(node_respond_event_dict) == node_respond_event
