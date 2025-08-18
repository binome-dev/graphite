import pytest

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.workflow_events.workflow_respond_event import (
    WorkflowRespondEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.topic_types import TopicType


@pytest.fixture
def workflow_respond_event() -> WorkflowRespondEvent:
    return WorkflowRespondEvent(
        event_id="test_id",
        event_type="WorkflowRespond",
        timestamp="2009-02-13T23:31:30+00:00",
        workflow_id="test_id",
        workflow_name="test_workflow",
        workflow_type="test_type",
        invoke_context=InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        ),
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
    )


@pytest.fixture
def workflow_respond_event_dict():
    return {
        "event_id": "test_id",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "WorkflowRespond",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "event_context": {
            "workflow_id": "test_id",
            "workflow_name": "test_workflow",
            "workflow_type": "test_type",
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


def test_workflow_respond_event_to_dict(
    workflow_respond_event: WorkflowRespondEvent, workflow_respond_event_dict
):
    assert workflow_respond_event.to_dict() == workflow_respond_event_dict


def test_workflow_respond_event_from_dict(
    workflow_respond_event_dict, workflow_respond_event
):
    assert (
        WorkflowRespondEvent.from_dict(workflow_respond_event_dict)
        == workflow_respond_event
    )
