import pytest

from grafi.common.events.assistant_events.assistant_failed_event import (
    AssistantFailedEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.topic_types import TopicType


@pytest.fixture
def assistant_failed_event() -> AssistantFailedEvent:
    return AssistantFailedEvent(
        event_id="test_id",
        event_type="AssistantFailed",
        timestamp="2009-02-13T23:31:30+00:00",
        assistant_id="test_id",
        assistant_name="test_assistant",
        assistant_type="test_type",
        input_data=PublishToTopicEvent(
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
                )
            ],
        ),
        error="error",
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
    )


@pytest.fixture
def assistant_failed_event_dict():
    return {
        "event_id": "test_id",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "AssistantFailed",
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
            "input_data": {
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
            "error": "error",
        },
    }


def test_assistant_failed_event_dict(
    assistant_failed_event: AssistantFailedEvent, assistant_failed_event_dict
):
    assert assistant_failed_event.to_dict() == assistant_failed_event_dict


def test_assistant_failed_event(assistant_failed_event_dict, assistant_failed_event):
    assert (
        AssistantFailedEvent.from_dict(assistant_failed_event_dict)
        == assistant_failed_event
    )
