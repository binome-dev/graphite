from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.topics.topic_types import TopicType
from grafi.workflows.impl.utils import consumption_of


def _context() -> InvokeContext:
    return InvokeContext(
        conversation_id="test-conversation",
        invoke_id="test-invoke",
        assistant_request_id="test-request",
    )


class TestConsumptionOf:
    def test_records_the_consumer_taking_the_publication(self) -> None:
        publication = PublishToTopicEvent(
            name="topic1",
            type=TopicType.AGENT_OUTPUT_TOPIC_TYPE,
            publisher_name="producer",
            publisher_type="Node",
            invoke_context=_context(),
            offset=3,
            data=[Message(role="user", content="Test")],
        )

        consumed = consumption_of(publication, "test_node", "test_type")

        assert isinstance(consumed, ConsumeFromTopicEvent)
        assert (consumed.consumer_name, consumed.consumer_type) == (
            "test_node",
            "test_type",
        )
        assert (consumed.name, consumed.type, consumed.offset) == (
            "topic1",
            TopicType.AGENT_OUTPUT_TOPIC_TYPE,
            3,
        )
        assert consumed.invoke_context == publication.invoke_context
        assert consumed.data == publication.data
