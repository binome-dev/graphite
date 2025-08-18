import pytest

from grafi.common.events.assistant_events.assistant_respond_event import (
    AssistantRespondEvent,
)
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.topic_types import TopicType


@pytest.fixture
def assistant_respond_event() -> AssistantRespondEvent:
    return AssistantRespondEvent(
        event_id="test_id",
        event_type="AssistantRespond",
        timestamp="2009-02-13T23:31:30+00:00",
        assistant_id="test_id",
        assistant_name="test_assistant",
        assistant_type="test_type",
        input_event=PublishToTopicEvent(
            event_id="test_id",
            timestamp="2009-02-13T23:31:30+00:00",
            invoke_context=InvokeContext(
                conversation_id="conversation_id",
                invoke_id="invoke_id",
                assistant_request_id="assistant_request_id",
            ),
            topic_name="test_output_topic",
            topic_type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
            publisher_name="test_assistant",
            publisher_type="test_type",
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
        ),
        output_data=[
            ConsumeFromTopicEvent(
                event_id="test_id",
                topic_name="test_topic",
                topic_type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
                node_id="test_node_id",
                consumer_name="test_node",
                consumer_type="test_type",
                offset=-1,
                timestamp="2009-02-13T23:31:30+00:00",
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
            )
        ],
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
    )


@pytest.fixture
def assistant_respond_event_dict():
    return {
        "event_id": "test_id",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "AssistantRespond",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
            "assistant_id": "test_id",
            "assistant_name": "test_assistant",
            "assistant_type": "test_type",
            "invoke_context": {
                "conversation_id": "conversation_id",
                "invoke_id": "invoke_id",
                "assistant_request_id": "assistant_request_id",
                "user_id": "",
                "kwargs": {},
            },
        },
        "data": {
            "input_event": {
                "event_context": {
                    "consumed_event_ids": [],
                    "publisher_name": "test_assistant",
                    "publisher_type": "test_type",
                    "topic_name": "test_output_topic",
                    "topic_type": "AgentOutputTopic",
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
                "event_type": "PublishToTopic",
                "timestamp": "2009-02-13T23:31:30+00:00",
                "data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}]',
            },
            "output_data": [
                {
                    "event_context": {
                        "consumer_name": "test_node",
                        "consumer_type": "test_type",
                        "topic_name": "test_topic",
                        "topic_type": "AgentOutputTopic",
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
                    "data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}, {"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f6", "timestamp": 1737138526189605000, "content": "Hello, Grafi, I am doing well, thank you.", "refusal": null, "annotations": null, "audio": null, "role": "assistant", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null, "is_streaming": false}]',
                }
            ],
        },
    }


def test_assistant_respond_event_dict(
    assistant_respond_event: AssistantRespondEvent, assistant_respond_event_dict
):
    assert assistant_respond_event.to_dict() == assistant_respond_event_dict


def test_assistant_respond_event(assistant_respond_event_dict, assistant_respond_event):
    assert (
        AssistantRespondEvent.from_dict(assistant_respond_event_dict)
        == assistant_respond_event
    )
