from unittest.mock import Mock

import pytest

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Message
from grafi.common.topics.human_request_topic import HUMAN_REQUEST_TOPIC
from grafi.common.topics.human_request_topic import HumanRequestTopic
from grafi.common.topics.human_request_topic import HumanRequestTopicBuilder
from grafi.common.topics.human_request_topic import human_request_topic


class TestHumanRequestTopic:
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
            Message(content="How can I help?", role="assistant"),
        ]

    @pytest.fixture
    def sample_consumed_events(self, sample_invoke_context):
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
    def sample_output_topic_event(self, sample_invoke_context, sample_messages):
        return OutputTopicEvent(
            event_id="output_event_1",
            invoke_context=sample_invoke_context,
            topic_name="test_topic",
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=sample_messages,
            consumed_event_ids=["consumed_1"],
            offset=0,
        )

    @pytest.fixture
    def sample_publish_to_topic_event(self, sample_invoke_context, sample_messages):
        return PublishToTopicEvent(
            event_id="publish_event_1",
            invoke_context=sample_invoke_context,
            topic_name="test_topic",
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=sample_messages,
            consumed_event_ids=["consumed_1"],
            offset=0,
        )

    @pytest.fixture
    def human_request_topic_instance(self):
        topic = HumanRequestTopic(name="test_human_request_topic")
        yield topic
        # Cleanup after test
        topic.reset()

    def test_human_request_topic_creation(self):
        """Test creating a HumanRequestTopic with default values."""
        topic = HumanRequestTopic()

        assert topic.name == HUMAN_REQUEST_TOPIC
        assert topic.publish_to_human_event_handler is None
        assert topic.publish_event_handler is None
        assert len(topic.event_cache) == 0
        assert topic.consumption_offsets == {}

    def test_human_request_topic_with_custom_name(self):
        """Test creating a HumanRequestTopic with custom name."""
        topic = HumanRequestTopic(name="custom_human_topic")

        assert topic.name == "custom_human_topic"

    def test_builder_pattern(self):
        """Test using the builder pattern to create HumanRequestTopic."""
        builder = HumanRequestTopic.builder()
        assert isinstance(builder, HumanRequestTopicBuilder)

        topic = builder.build()
        assert isinstance(topic, HumanRequestTopic)

    def test_builder_with_publish_event_handler(self):
        """Test builder with publish event handler."""
        handler = Mock()

        topic = HumanRequestTopic.builder().publish_event_handler(handler).build()

        assert topic.publish_event_handler == handler

    def test_builder_with_publish_to_human_event_handler(self):
        """Test builder with publish to human event handler."""
        handler = Mock()

        topic = (
            HumanRequestTopic.builder().publish_to_human_event_handler(handler).build()
        )

        assert topic.publish_to_human_event_handler == handler

    def test_builder_with_both_handlers(self):
        """Test builder with both event handlers."""
        publish_handler = Mock()
        human_handler = Mock()

        topic = (
            HumanRequestTopic.builder()
            .publish_event_handler(publish_handler)
            .publish_to_human_event_handler(human_handler)
            .build()
        )

        assert topic.publish_event_handler == publish_handler
        assert topic.publish_to_human_event_handler == human_handler

    def test_can_append_user_input_new_consumer(
        self, human_request_topic_instance, sample_output_topic_event
    ):
        """Test can_append_user_input with new consumer (no prior consumption)."""
        # Add an event to the topic using the proper method
        human_request_topic_instance.add_event(sample_output_topic_event)

        # New consumer should be able to append
        result = human_request_topic_instance.can_append_user_input(
            "new_consumer", sample_output_topic_event
        )
        assert result is True

    def test_can_append_user_input_consumer_caught_up(
        self, human_request_topic_instance, sample_output_topic_event
    ):
        """Test can_append_user_input when consumer is caught up."""
        # Add an event to the topic using the proper method
        human_request_topic_instance.add_event(sample_output_topic_event)

        # Consumer has consumed all events
        human_request_topic_instance.consumption_offsets["consumer1"] = 1

        result = human_request_topic_instance.can_append_user_input(
            "consumer1", sample_output_topic_event
        )
        assert result is False

    def test_can_append_user_input_event_already_consumed(
        self, human_request_topic_instance, sample_output_topic_event
    ):
        """Test can_append_user_input when event was already consumed."""
        # Add multiple events to the topic using proper methods
        human_request_topic_instance.add_event(sample_output_topic_event)
        # Create a second event with offset 1
        second_event = OutputTopicEvent(
            event_id="second_event",
            invoke_context=sample_output_topic_event.invoke_context,
            topic_name=sample_output_topic_event.topic_name,
            publisher_name=sample_output_topic_event.publisher_name,
            publisher_type=sample_output_topic_event.publisher_type,
            data=sample_output_topic_event.data,
            consumed_event_ids=sample_output_topic_event.consumed_event_ids,
            offset=1,
        )
        human_request_topic_instance.add_event(second_event)

        # Consumer has consumed more than the event offset
        human_request_topic_instance.consumption_offsets["consumer1"] = 1

        # Try to append an event with offset 0 (already consumed)
        old_event = OutputTopicEvent(
            event_id="old_event",
            invoke_context=sample_output_topic_event.invoke_context,
            topic_name="test_topic",
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=sample_output_topic_event.data,
            consumed_event_ids=[],
            offset=0,  # Already consumed
        )

        result = human_request_topic_instance.can_append_user_input(
            "consumer1", old_event
        )
        assert result is False

    def test_can_append_user_input_valid_scenario(
        self, human_request_topic_instance, sample_output_topic_event
    ):
        """Test can_append_user_input in valid scenario."""
        # Add an event to the topic using proper method
        human_request_topic_instance.add_event(sample_output_topic_event)

        # Consumer has consumed some but not all events
        human_request_topic_instance.consumption_offsets["consumer1"] = 0

        # New event with offset 1
        new_event = OutputTopicEvent(
            event_id="new_event",
            invoke_context=sample_output_topic_event.invoke_context,
            topic_name="test_topic",
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=sample_output_topic_event.data,
            consumed_event_ids=[],
            offset=1,
        )

        result = human_request_topic_instance.can_append_user_input(
            "consumer1", new_event
        )
        assert result is True

    def test_publish_data_with_condition_true(
        self,
        human_request_topic_instance,
        sample_invoke_context,
        sample_messages,
        sample_consumed_events,
    ):
        """Test publishing data when condition is met."""
        # Mock condition to return True
        human_request_topic_instance.condition = Mock(return_value=True)

        event = human_request_topic_instance.publish_data(
            invoke_context=sample_invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=sample_messages,
            consumed_events=sample_consumed_events,
        )

        assert event is not None
        assert isinstance(event, OutputTopicEvent)
        assert event.publisher_name == "test_publisher"
        assert event.publisher_type == "test_type"
        assert event.data == sample_messages
        assert event.consumed_event_ids == ["test_id_1", "test_id_2"]
        assert event.offset == 0
        assert len(human_request_topic_instance.event_cache) == 1

    def test_publish_data_with_condition_false(
        self,
        human_request_topic_instance,
        sample_invoke_context,
        sample_messages,
        sample_consumed_events,
    ):
        """Test publishing data when condition is not met."""
        # Mock condition to return False
        human_request_topic_instance.condition = Mock(return_value=False)

        event = human_request_topic_instance.publish_data(
            invoke_context=sample_invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=sample_messages,
            consumed_events=sample_consumed_events,
        )

        assert event is None
        assert len(human_request_topic_instance.event_cache) == 0

    def test_publish_data_with_human_event_handler(
        self,
        human_request_topic_instance,
        sample_invoke_context,
        sample_messages,
        sample_consumed_events,
    ):
        """Test publishing data with human event handler."""
        handler = Mock()
        human_request_topic_instance.publish_to_human_event_handler = handler
        human_request_topic_instance.condition = Mock(return_value=True)

        event = human_request_topic_instance.publish_data(
            invoke_context=sample_invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=sample_messages,
            consumed_events=sample_consumed_events,
        )

        handler.assert_called_once_with(event)

    def test_append_user_input_with_output_topic_event(
        self, human_request_topic_instance, sample_output_topic_event, sample_messages
    ):
        """Test appending user input with OutputTopicEvent."""
        human_request_topic_instance.condition = Mock(return_value=True)

        event = human_request_topic_instance.append_user_input(
            user_input_event=sample_output_topic_event, data=sample_messages
        )

        assert event is not None
        assert isinstance(event, PublishToTopicEvent)
        assert event.invoke_context == sample_output_topic_event.invoke_context
        assert event.publisher_name == sample_output_topic_event.publisher_name
        assert event.publisher_type == sample_output_topic_event.publisher_type
        assert event.data == sample_messages
        assert event.consumed_event_ids == sample_output_topic_event.consumed_event_ids
        assert event.offset == 0
        assert len(human_request_topic_instance.event_cache) == 1

    def test_append_user_input_with_publish_to_topic_event(
        self,
        human_request_topic_instance,
        sample_publish_to_topic_event,
        sample_messages,
    ):
        """Test appending user input with PublishToTopicEvent."""
        human_request_topic_instance.condition = Mock(return_value=True)

        event = human_request_topic_instance.append_user_input(
            user_input_event=sample_publish_to_topic_event, data=sample_messages
        )

        assert event is not None
        assert isinstance(event, PublishToTopicEvent)
        assert event.invoke_context == sample_publish_to_topic_event.invoke_context
        assert event.publisher_name == sample_publish_to_topic_event.publisher_name
        assert event.publisher_type == sample_publish_to_topic_event.publisher_type
        assert event.data == sample_messages
        assert (
            event.consumed_event_ids == sample_publish_to_topic_event.consumed_event_ids
        )

    def test_append_user_input_with_condition_false(
        self, human_request_topic_instance, sample_output_topic_event, sample_messages
    ):
        """Test appending user input when condition is not met."""
        human_request_topic_instance.condition = Mock(return_value=False)

        event = human_request_topic_instance.append_user_input(
            user_input_event=sample_output_topic_event, data=sample_messages
        )

        assert event is None
        assert len(human_request_topic_instance.event_cache) == 0

    def test_append_user_input_with_publish_event_handler(
        self, human_request_topic_instance, sample_output_topic_event, sample_messages
    ):
        """Test appending user input with publish event handler."""
        handler = Mock()
        human_request_topic_instance.publish_event_handler = handler
        human_request_topic_instance.condition = Mock(return_value=True)

        event = human_request_topic_instance.append_user_input(
            user_input_event=sample_output_topic_event, data=sample_messages
        )

        handler.assert_called_once_with(event)

    def test_append_user_input_offset_increments(
        self, human_request_topic_instance, sample_output_topic_event, sample_messages
    ):
        """Test that offset increments correctly when appending multiple user inputs."""
        human_request_topic_instance.condition = Mock(return_value=True)

        # Add first event
        event1 = human_request_topic_instance.append_user_input(
            user_input_event=sample_output_topic_event, data=sample_messages
        )

        # Add second event
        event2 = human_request_topic_instance.append_user_input(
            user_input_event=sample_output_topic_event, data=sample_messages
        )

        assert event1.offset == 0
        assert event2.offset == 1
        assert len(human_request_topic_instance.event_cache) == 2

    def test_publish_data_offset_increments(
        self,
        human_request_topic_instance,
        sample_invoke_context,
        sample_messages,
        sample_consumed_events,
    ):
        """Test that offset increments correctly when publishing multiple data."""
        human_request_topic_instance.condition = Mock(return_value=True)

        # Publish first event
        event1 = human_request_topic_instance.publish_data(
            invoke_context=sample_invoke_context,
            publisher_name="publisher1",
            publisher_type="type1",
            data=sample_messages,
            consumed_events=sample_consumed_events,
        )

        # Publish second event
        event2 = human_request_topic_instance.publish_data(
            invoke_context=sample_invoke_context,
            publisher_name="publisher2",
            publisher_type="type2",
            data=sample_messages,
            consumed_events=sample_consumed_events,
        )

        assert event1.offset == 0
        assert event2.offset == 1
        assert len(human_request_topic_instance.event_cache) == 2

    def test_global_human_request_topic(self):
        """Test the global human_request_topic instance."""
        assert human_request_topic.name == HUMAN_REQUEST_TOPIC
        assert isinstance(human_request_topic, HumanRequestTopic)

    def test_mixed_event_types_in_topic(
        self,
        human_request_topic_instance,
        sample_invoke_context,
        sample_messages,
        sample_consumed_events,
        sample_output_topic_event,
    ):
        """Test that topic can handle both OutputTopicEvent and PublishToTopicEvent."""
        human_request_topic_instance.condition = Mock(return_value=True)

        # Publish an OutputTopicEvent
        output_event = human_request_topic_instance.publish_data(
            invoke_context=sample_invoke_context,
            publisher_name="publisher1",
            publisher_type="type1",
            data=sample_messages,
            consumed_events=sample_consumed_events,
        )

        # Append a PublishToTopicEvent
        publish_event = human_request_topic_instance.append_user_input(
            user_input_event=sample_output_topic_event, data=sample_messages
        )

        assert len(human_request_topic_instance.event_cache) == 2
        assert isinstance(
            human_request_topic_instance.event_cache.get(0), OutputTopicEvent
        )
        assert isinstance(
            human_request_topic_instance.event_cache.get(1), PublishToTopicEvent
        )
        assert output_event.offset == 0
        assert publish_event.offset == 1

    def test_can_append_user_input_with_publish_to_topic_event(
        self, human_request_topic_instance, sample_publish_to_topic_event
    ):
        """Test can_append_user_input works with PublishToTopicEvent."""
        # Add an event to the topic using proper method
        human_request_topic_instance.add_event(sample_publish_to_topic_event)

        # New consumer should be able to append
        result = human_request_topic_instance.can_append_user_input(
            "new_consumer", sample_publish_to_topic_event
        )
        assert result is True

    def test_empty_consumed_events_list(
        self, human_request_topic_instance, sample_invoke_context, sample_messages
    ):
        """Test publishing data with empty consumed events list."""
        human_request_topic_instance.condition = Mock(return_value=True)

        event = human_request_topic_instance.publish_data(
            invoke_context=sample_invoke_context,
            publisher_name="test_publisher",
            publisher_type="test_type",
            data=sample_messages,
            consumed_events=[],  # Empty list
        )

        assert event is not None
        assert event.consumed_event_ids == []
