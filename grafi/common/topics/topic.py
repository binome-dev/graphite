from typing import Callable
from typing import List
from typing import Optional
from typing import Self

from loguru import logger
from pydantic import Field

from grafi.common.events.topic_events.consume_from_topic_event import (
    ConsumeFromTopicEvent,
)
from grafi.common.events.topic_events.publish_to_topic_event import PublishToTopicEvent
from grafi.common.events.topic_events.topic_event import TopicEvent
from grafi.common.models.execution_context import ExecutionContext
from grafi.common.models.message import Messages
from grafi.common.topics.topic_base import AGENT_INPUT_TOPIC
from grafi.common.topics.topic_base import TopicBase


class Topic(TopicBase):
    """
    Represents a topic in a message queue system.
    """

    topic_events: List[TopicEvent] = []

    publish_event_handler: Optional[Callable[[PublishToTopicEvent], None]] = Field(
        default=None
    )

    class Builder(TopicBase.Builder):

        _topic: "Topic"

        def __init__(self) -> None:
            self._topic = self._init_topic()

        def _init_topic(self) -> "Topic":
            return Topic.model_construct()

        def publish_event_handler(
            self, publish_event_handler: Callable[[PublishToTopicEvent], None]
        ) -> Self:
            self._topic.publish_event_handler = publish_event_handler
            return self

        def build(self) -> "Topic":
            return self._topic

    def publish_data(
        self,
        execution_context: ExecutionContext,
        publisher_name: str,
        publisher_type: str,
        data: Messages,
        consumed_events: List[ConsumeFromTopicEvent],
    ) -> PublishToTopicEvent:
        """
        Publishes a message's event ID to this topic if it meets the condition.
        """
        if self.condition(data):
            event = PublishToTopicEvent(
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
            if self.publish_event_handler:
                self.publish_event_handler(event)
            logger.info(
                f"[{self.name}] Message published with event_id: {event.event_id}"
            )
            return event
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None


agent_input_topic = Topic(name=AGENT_INPUT_TOPIC)
