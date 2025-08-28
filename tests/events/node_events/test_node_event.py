"""Helper functions for node event tests."""

from typing import List

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.topic_types import TopicType


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