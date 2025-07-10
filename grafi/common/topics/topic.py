from typing import Any
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
from grafi.common.models.invoke_context import InvokeContext
from grafi.common.models.message import Messages
from grafi.common.topics.topic_base import AGENT_INPUT_TOPIC
from grafi.common.topics.topic_base import TopicBase
from grafi.common.topics.topic_base import TopicBaseBuilder


class Topic(TopicBase):
    """
    Represents a topic in a message queue system.
    """

    publish_event_handler: Optional[Callable[[PublishToTopicEvent], None]] = Field(
        default=None
    )

    @classmethod
    def builder(cls) -> "TopicBuilder":
        """
        Returns a builder for Topic.
        """
        return TopicBuilder(cls)

    def publish_data(
        self,
        invoke_context: InvokeContext,
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
                invoke_context=invoke_context,
                topic_name=self.name,
                publisher_name=publisher_name,
                publisher_type=publisher_type,
                data=data,
                consumed_event_ids=[
                    consumed_event.event_id for consumed_event in consumed_events
                ],
                offset=self.total_published,
            )
            # Add event to cache and update total_published
            self.add_event(event)
            if self.publish_event_handler:
                self.publish_event_handler(event)
            logger.info(
                f"[{self.name}] Message published with event_id: {event.event_id}"
            )
            return event
        else:
            logger.info(f"[{self.name}] Message NOT published (condition not met)")
            return None

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the topic to a dictionary.
        """
        return {
            **super().to_dict(),
        }


class TopicBuilder(TopicBaseBuilder[Topic]):
    """
    Builder for creating instances of Topic.
    """

    def publish_event_handler(
        self, publish_event_handler: Callable[[PublishToTopicEvent], None]
    ) -> Self:
        self.kwargs["publish_event_handler"] = publish_event_handler
        return self


agent_input_topic = Topic(name=AGENT_INPUT_TOPIC)
