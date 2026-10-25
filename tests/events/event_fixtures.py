"""Shared pieces of the event serialization tests: the values the events are
made of, the stored (JSON) form of those values, and the round trip a durable
store makes an event take."""

import json
from typing import Any
from typing import Dict
from typing import List

from grafi.common.events.component_events import AssistantFailedEvent
from grafi.common.events.component_events import AssistantInvokeEvent
from grafi.common.events.component_events import AssistantRespondEvent
from grafi.common.events.component_events import NodeFailedEvent
from grafi.common.events.component_events import NodeInvokeEvent
from grafi.common.events.component_events import NodeRespondEvent
from grafi.common.events.component_events import ToolFailedEvent
from grafi.common.events.component_events import ToolInvokeEvent
from grafi.common.events.component_events import ToolRespondEvent
from grafi.common.events.component_events import WorkflowFailedEvent
from grafi.common.events.component_events import WorkflowInvokeEvent
from grafi.common.events.component_events import WorkflowRespondEvent
from grafi.common.events.event import Event
from grafi.common.events.event_codec import default_event_codec
from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_types import TopicType

TIMESTAMP = "2009-02-13T23:31:30+00:00"
# TIMESTAMP as an event's JSON form writes it.
TIMESTAMP_JSON = "2009-02-13T23:31:30Z"

INVOKE_CONTEXT_JSON: Dict[str, Any] = {
    "conversation_id": "conversation_id",
    "invoke_id": "invoke_id",
    "assistant_request_id": "assistant_request_id",
    "user_id": "",
    "kwargs": {},
}

HELLO_JSON: Dict[str, Any] = {
    "name": None,
    "message_id": "ea72df51439b42e4a43b217c9bca63f5",
    "timestamp": 1737138526189505000,
    "content": "Hello, my name is Grafi, how are you doing?",
    "refusal": None,
    "annotations": None,
    "audio": None,
    "role": "user",
    "tool_call_id": None,
    "tools": None,
    "function_call": None,
    "tool_calls": None,
}

REPLY_JSON: Dict[str, Any] = {
    **HELLO_JSON,
    "message_id": "ea72df51439b42e4a43b217c9bca63f6",
    "timestamp": 1737138526189605000,
    "content": "Hello, Grafi, I am doing well, thank you.",
    "role": "assistant",
}


def invoke_context() -> InvokeContext:
    return InvokeContext(
        conversation_id="conversation_id",
        invoke_id="invoke_id",
        assistant_request_id="assistant_request_id",
    )


def hello() -> Message:
    """The user's message (HELLO_JSON)."""
    return Message(
        message_id="ea72df51439b42e4a43b217c9bca63f5",
        timestamp=1737138526189505000,
        role="user",
        content="Hello, my name is Grafi, how are you doing?",
    )


def reply() -> Message:
    """The assistant's reply (REPLY_JSON)."""
    return Message(
        message_id="ea72df51439b42e4a43b217c9bca63f6",
        timestamp=1737138526189605000,
        role="assistant",
        content="Hello, Grafi, I am doing well, thank you.",
    )


# A version 1 invoke context, as InvokeContext.model_dump() wrote it.
INVOKE_CONTEXT_V1: Dict[str, Any] = dict(INVOKE_CONTEXT_JSON)

HELLO_V1 = '{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null}'
REPLY_V1 = '{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f6", "timestamp": 1737138526189605000, "content": "Hello, Grafi, I am doing well, thank you.", "refusal": null, "annotations": null, "audio": null, "role": "assistant", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null}'


def request() -> PublishToTopicEvent:
    """The input of the workflow and assistant events."""
    return PublishToTopicEvent(
        event_id="test_id",
        timestamp=TIMESTAMP,
        invoke_context=invoke_context(),
        name="test_output_topic",
        type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
        publisher_name="test_assistant",
        publisher_type="test_type",
        data=[hello()],
    )


def request_json() -> Dict[str, Any]:
    """request() in its stored form."""
    return {
        "event_id": "test_id",
        "event_version": 2,
        "invoke_context": INVOKE_CONTEXT_JSON,
        "event_type": "PublishToTopic",
        "timestamp": TIMESTAMP_JSON,
        "name": "test_output_topic",
        "type": "AgentOutputTopic",
        "offset": -1,
        "data": [HELLO_JSON],
        "emission_id": None,
        "consumed_event_ids": [],
        "publisher_name": "test_assistant",
        "publisher_type": "test_type",
    }


def request_v1() -> Dict[str, Any]:
    """request() as version 1 stored it."""
    return {
        "event_context": {
            "consumed_event_ids": [],
            "publisher_name": "test_assistant",
            "publisher_type": "test_type",
            "name": "test_output_topic",
            "type": "AgentOutputTopic",
            "offset": -1,
            "invoke_context": INVOKE_CONTEXT_V1,
        },
        "event_id": "test_id",
        "event_version": "1.0",
        "assistant_request_id": "assistant_request_id",
        "event_type": "PublishToTopic",
        "timestamp": "2009-02-13T23:31:30+00:00",
        "data": f"[{HELLO_V1}]",
    }


def answers() -> List[ConsumeFromTopicEvent]:
    """The output of the workflow and assistant events."""
    return [
        ConsumeFromTopicEvent(
            event_id="test_id",
            name="test_topic",
            type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
            consumer_name="test_node",
            consumer_type="test_type",
            offset=-1,
            timestamp=TIMESTAMP,
            invoke_context=invoke_context(),
            data=[hello(), reply()],
        )
    ]


def answers_json() -> List[Dict[str, Any]]:
    """answers() in their stored form."""
    return [
        {
            "event_id": "test_id",
            "event_version": 2,
            "invoke_context": INVOKE_CONTEXT_JSON,
            "event_type": "ConsumeFromTopic",
            "timestamp": TIMESTAMP_JSON,
            "name": "test_topic",
            "type": "AgentOutputTopic",
            "offset": -1,
            "data": [HELLO_JSON, REPLY_JSON],
            "consumer_name": "test_node",
            "consumer_type": "test_type",
        }
    ]


def answers_v1() -> List[Dict[str, Any]]:
    """answers() as version 1 stored them."""
    return [
        {
            "event_context": {
                "consumer_name": "test_node",
                "consumer_type": "test_type",
                "name": "test_topic",
                "type": "AgentOutputTopic",
                "offset": -1,
                "invoke_context": INVOKE_CONTEXT_V1,
            },
            "event_id": "test_id",
            "event_version": "1.0",
            "assistant_request_id": "assistant_request_id",
            "event_type": "ConsumeFromTopic",
            "timestamp": "2009-02-13T23:31:30+00:00",
            "data": f"[{HELLO_V1}, {REPLY_V1}]",
        }
    ]


def stored(event: Event) -> Dict[str, Any]:
    """``event`` as a durable store keeps it: encoded, written as JSON text and
    read back."""
    return json.loads(json.dumps(default_event_codec.encode(event)))


def round_trip(event: Event) -> Event:
    """``event`` decoded from its stored form."""
    return default_event_codec.decode(stored(event))


def every_event() -> List[Event]:
    """An event of each type the default codec decodes, with nested events, a
    node that published nothing, error details and an assistant's model."""
    context = invoke_context()
    consumed = ConsumeFromTopicEvent(
        event_id="consumed",
        name="input",
        type=TopicType.AGENT_INPUT_TOPIC_TYPE,
        offset=0,
        consumer_name="node",
        consumer_type="Node",
        invoke_context=context,
        data=[hello()],
        timestamp=TIMESTAMP,
    )
    published = PublishToTopicEvent(
        event_id="published",
        emission_id="emission",
        name="output",
        type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
        offset=1,
        consumed_event_ids=["consumed"],
        publisher_name="node",
        publisher_type="Node",
        invoke_context=context,
        data=[reply()],
        timestamp=TIMESTAMP,
    )
    node = {
        "id": "node_id",
        "name": "node",
        "type": "Node",
        "subscribed_topics": ["input"],
        "publish_to_topics": ["output"],
        "invoke_context": context,
        "input_data": [consumed],
        "timestamp": TIMESTAMP,
    }
    tool = {
        "id": "tool_id",
        "name": "tool",
        "type": "FunctionTool",
        "invoke_context": context,
        "input_data": [hello()],
        "timestamp": TIMESTAMP,
    }
    workflow = {
        "id": "workflow_id",
        "name": "workflow",
        "type": "EventDrivenWorkflow",
        "invoke_context": context,
        "input_data": published,
        "timestamp": TIMESTAMP,
    }
    assistant = {**workflow, "id": "assistant_id", "name": "assistant"}
    details = {"error_type": "ValueError", "message": "boom", "cause": None}
    return [
        TopicEvent(
            event_id="topic",
            name="topic",
            invoke_context=context,
            data=[hello()],
            timestamp=TIMESTAMP,
        ),
        consumed,
        published,
        NodeInvokeEvent(event_id="node_invoke", **node),
        NodeRespondEvent(event_id="node_respond", output_data=published, **node),
        NodeRespondEvent(event_id="node_respond_nothing", output_data=None, **node),
        NodeFailedEvent(
            event_id="node_failed", error="boom", error_details=details, **node
        ),
        ToolInvokeEvent(event_id="tool_invoke", **tool),
        ToolRespondEvent(event_id="tool_respond", output_data=[reply()], **tool),
        ToolFailedEvent(event_id="tool_failed", error="boom", **tool),
        WorkflowInvokeEvent(event_id="workflow_invoke", **workflow),
        WorkflowRespondEvent(
            event_id="workflow_respond", output_data=[consumed], **workflow
        ),
        WorkflowFailedEvent(event_id="workflow_failed", error="boom", **workflow),
        AssistantInvokeEvent(event_id="assistant_invoke", model="gpt-4o", **assistant),
        AssistantRespondEvent(
            event_id="assistant_respond", output_data=[consumed], **assistant
        ),
        AssistantFailedEvent(
            event_id="assistant_failed",
            error="boom",
            error_details=details,
            **assistant,
        ),
    ]
