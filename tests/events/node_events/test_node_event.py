"""Helper functions for node event tests."""

from typing import Any
from typing import Dict
from typing import List

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_types import TopicType
from tests.events.event_fixtures import HELLO_JSON
from tests.events.event_fixtures import INVOKE_CONTEXT_JSON
from tests.events.event_fixtures import TIMESTAMP_JSON


def get_consumed_events(
    messages: List[Message], invoke_context: InvokeContext = None
) -> List[ConsumeFromTopicEvent]:
    """Create sample consumed events for testing."""
    if invoke_context is None:
        invoke_context = InvokeContext(
            conversation_id="conversation_id",
            invoke_id="invoke_id",
            assistant_request_id="assistant_request_id",
        )
    return [
        ConsumeFromTopicEvent(
            event_id="test_id",
            name="test_topic",
            type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
            consumer_name="test_node",
            consumer_type="test_type",
            offset=-1,
            timestamp="2009-02-13T23:31:30+00:00",
            invoke_context=invoke_context,
            data=messages,
        )
    ]


def consumed_events_json() -> List[Dict[str, Any]]:
    """get_consumed_events([hello()]) in its stored form."""
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
            "data": [HELLO_JSON],
            "consumer_name": "test_node",
            "consumer_type": "test_type",
        }
    ]


def consumed_events_v1() -> List[Dict[str, Any]]:
    """get_consumed_events([hello()]) as version 1 stored it."""
    return [
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
            "data": '[{"name": null, "message_id": "ea72df51439b42e4a43b217c9bca63f5", "timestamp": 1737138526189505000, "content": "Hello, my name is Grafi, how are you doing?", "refusal": null, "annotations": null, "audio": null, "role": "user", "tool_call_id": null, "tools": null, "function_call": null, "tool_calls": null}]',
        }
    ]
