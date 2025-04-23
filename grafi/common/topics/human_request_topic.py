from typing import Callable
from typing import List
from typing import Optional
from typing import Self

from loguru import logger
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.output_topic_event import OutputTopicEvent
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.topics.topic_base import AGENT_RESERVED_TOPICS
from grafi.common.topics.topic_base import HUMAN_REQUEST_TOPIC
from grafi.common.topics.topic_base import TopicBase


AGENT_RESERVED_TOPICS.extend([HUMAN_REQUEST_TOPIC])


class HumanRequestTopic(TopicBase):
    """
    Represents a topic for human request events.
    """

    name: str = HUMAN_REQUEST_TOPIC
    publish_to_human_event_handler: Optional[Callable[[OutputTopicEvent], None]] = (
        Field(default=None)
    )
    publish_event_handler: Optional[Callable[[PublishToTopicEvent], None]] = Field(
        default=None
    )

    class Builder(TopicBase.Builder):

        _topic: "HumanRequestTopic"

        def __init__(self) -> None:
            self._topic = self._init_topic()

        def _init_topic(self) -> "HumanRequestTopic":
            return HumanRequestTopic.model_construct()

        def publish_event_handler(
            self, publish_event_handler: Callable[[PublishToTopicEvent], None]
        ) -> Self:
            self._topic.publish_event_handler = publish_event_handler
            return self

        def publish_to_human_event_handler(
            self, publish_event_handler: Callable[[OutputTopicEvent], None]
        ) -> Self:
            self._topic.publish_to_human_event_handler = publish_event_handler
            return self

        def build(self) -> "HumanRequestTopic":
            return self._topic

    def can_append_user_input(
        self, consumer_name: str, event: PublishToTopicEvent | OutputTopicEvent
    ) -> bool:
        already_consumed = self.consumption_offsets.get(consumer_name, 0)
        total_published = len(self.topic_events)
        if already_consumed >= total_published:
            return False

        if event.offset < already_consumed:
            return False

        return True

    def publish_data(
        self,
        execution_context: ExecutionContext,
        publisher_name: str,
        publisher_type: str,
        data: Messages,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> OutputTopicEvent:
        """
        Publishes a message's event ID to this topic if it meets the condition.
        """

        if self.condition(data):
            event = OutputTopicEvent(
                execution_context=execution_context,
                topic_name=self.name,
                publisher_name=publisher_name,
                publisher_type=publisher_type,
                data=data,
                consumed_event_ids=[
                    consumed_event.event_id for consumed_event in consumed_events
                ],
                offset=len(self.topic_events),
            )
            self.topic_events.append(event)
            if self.publish_to_human_event_handler:
                self.publish_to_human_event_handler(event)
            logger.info(
                f"[{self.name}] Message published with event_id: {event.event_id}"
            )
            return event
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None

    def append_user_input(
        self,
        user_input_event: PublishToTopicEvent | OutputTopicEvent,
        data: Messages,
    ) -> PublishToTopicEvent:
        """
        Publishes a message's event ID to this topic if it meets the condition.
        """
        if self.condition(data):
            event = PublishToTopicEvent(
                execution_context=user_input_event.execution_context,
                topic_name=self.name,
                publisher_name=user_input_event.publisher_name,
                publisher_type=user_input_event.publisher_type,
                data=data,
                consumed_event_ids=user_input_event.consumed_event_ids,
                offset=len(self.topic_events),
            )
            self.topic_events.append(event)
            if self.publish_event_handler:
                self.publish_event_handler(event)
            logger.info(
                f"[{self.name}] Message published with event_id: {event.event_id}"
            )
            return event
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None


human_request_topic = HumanRequestTopic(name=HUMAN_REQUEST_TOPIC)
