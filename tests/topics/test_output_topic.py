from unittest.mock import Mock

import pytest

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.output_topic import OutputTopic
from grafi.common.topics.topic_base import TopicType
from grafi.common.topics.topic_event_cache import TopicEventCache


agent_output_topic = OutputTopic(name="agent_output_topic")


class TestOutputTopic:
    @pytest.fixture
    def sample_invoke_context(self):
        return InvokeContext(
            user_id="test_user",
            conversation_id="test_conversation",
            invoke_id="test_invoke",
            assistant_request_id="test_assistant_request",
        )

    @pytest.fixture
    def sample_messages(self):
        return [
            Message(content="Hello", role="user"),
            Message(content="Hi there!", role="assistant"),
        ]

    @pytest.fixture
    def sample_consumed_events(self):
        return [
            ConsumeFromTopicEvent(
                event_id="test_id_1",
                event_type="ConsumeFromTopic",
                timestamp="2009-02-13T23:31:30+00:00",
                topic_name="test_topic",
                consumer_name="test_node",
                consumer_type="test_type",
                offset=0,
                invoke_context=InvokeContext(
                    user_id="test_user",
                    conversation_id="test_conversation",
                    invoke_id="test_invoke",
                    assistant_request_id="test_assistant_request",
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
                    )
                ],
            ),
            ConsumeFromTopicEvent(
                event_id="test_id_2",
                event_type="ConsumeFromTopic",
                timestamp="2009-02-13T23:31:30+00:00",
                topic_name="test_topic",
                consumer_name="test_node",
                consumer_type="test_type",
                offset=0,
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
                    )
                ],
            ),
        ]

    @pytest.fixture
    def output_topic(self):
        topic = OutputTopic(name="test_output_topic")
        yield topic
        # Cleanup after test
        topic.reset()

    def test_output_topic_creation(self):
        """Test creating an OutputTopic with default values."""
        topic = OutputTopic(name="agent_output_topic")

        assert topic.name == "agent_output_topic"
        assert topic.type == TopicType.AGENT_OUTPUT_TOPIC_TYPE
        assert isinstance(topic.event_cache, TopicEventCache)
        assert topic.publish_event_handler is None

    def test_output_topic_with_custom_name(self):
        """Test creating an OutputTopic with custom name."""
        topic = OutputTopic(name="custom_topic")

        assert topic.name == "custom_topic"

    def test_builder_with_publish_event_handler(self):
        """Test builder with publish event handler."""
        handler = Mock()

        topic = OutputTopic.builder().publish_event_handler(handler).build()

        assert topic.publish_event_handler == handler

    def test_publish_data_with_condition_true(
        self,
        output_topic,
        sample_invoke_context,
        sample_messages,
        sample_consumed_events,
    ):
        """Test publishing data when condition is met."""
        # Mock condition to return True
        output_topic.condition = Mock(return_value=True)

        event = output_topic.publish_data(
            PublishToTopicEvent(
                invoke_context=sample_invoke_context,
                publisher_name="test_publisher",
                publisher_type="test_type",
                data=sample_messages,
                consumed_event_ids=[event.event_id for event in sample_consumed_events],
            )
        )

        assert event is not None
        assert isinstance(event, PublishToTopicEvent)
        assert event.publisher_name == "test_publisher"
        assert event.publisher_type == "test_type"
        assert event.data == sample_messages
        assert event.consumed_event_ids == ["test_id_1", "test_id_2"]
        assert event.offset == 0
        assert output_topic.event_cache.num_events() == 1

    def test_publish_data_with_condition_false(
        self,
        output_topic,
        sample_invoke_context,
        sample_messages,
        sample_consumed_events,
    ):
        """Test publishing data when condition is not met."""
        # Mock condition to return False
        output_topic.condition = Mock(return_value=False)

        event = output_topic.publish_data(
            PublishToTopicEvent(
                invoke_context=sample_invoke_context,
                publisher_name="test_publisher",
                publisher_type="test_type",
                data=sample_messages,
                consumed_event_ids=[event.event_id for event in sample_consumed_events],
            )
        )

        assert event is None
        assert output_topic.event_cache.num_events() == 0

    def test_publish_data_with_event_handler(
        self,
        output_topic,
        sample_invoke_context,
        sample_messages,
        sample_consumed_events,
    ):
        """Test publishing data with event handler."""
        handler = Mock()
        output_topic.publish_event_handler = handler
        output_topic.condition = Mock(return_value=True)

        event = output_topic.publish_data(
            PublishToTopicEvent(
                invoke_context=sample_invoke_context,
                publisher_name="test_publisher",
                publisher_type="test_type",
                data=sample_messages,
                consumed_event_ids=[event.event_id for event in sample_consumed_events],
            )
        )

        handler.assert_called_once_with(event)
